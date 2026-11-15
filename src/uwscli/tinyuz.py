"""TinyUZ (github.com/sisong/tinyuz) encoder and decoder for wireless LED effects.

The fans decode LED effects with tinyuz in its default configuration: a 4-byte
little-endian dictionary size, then the code stream, literal lines enabled. The
vendor app compresses with a 4 KiB dictionary and stores in the header the
largest match distance it actually used; this encoder does the same, so its
output decodes with the upstream decoder and the vendor app's decoder.
"""

from __future__ import annotations

from collections.abc import Sequence

__all__ = [
    "TinyUZError",
    "compress",
    "compress_led_payload",
    "decompress",
    "generate_rainbow_frames",
]


class TinyUZError(RuntimeError):
    """Raised when TinyUZ compression or decompression fails."""


DICT_SIZE = 4096
_DICT_SIZE_BYTES = 4
_MIN_MATCH = 2  # tuz_kMinDictMatchLen
_MIN_LITERAL_LINE = 15  # tuz_kMinLiteralLen
_BIG_POS_FOR_LEN = (1 << 11) + (1 << 9) + (1 << 7) - 1  # needs one more byte of match
_MAX_MATCH = 4096  # well inside every decoder's length type
_CTRL_LITERAL_LINE = 1
_CTRL_CLIP_END = 2
_CTRL_STREAM_END = 3
_LEN_PACK_BITS = 1  # kDictLenPackBit
_POS_PACK_BITS = 2  # kDictPosLenPackBit
_MAX_CHAIN = 64
_NICE_MATCH = 128  # matches this long are taken without searching inside them


def _len_chunks(value: int, pack_bits: int) -> int:
    count = 1
    while value >= (1 << (count * pack_bits)):
        value -= 1 << (count * pack_bits)
        count += 1
    return count


def _len_bits(value: int, pack_bits: int) -> int:
    return _len_chunks(value, pack_bits) * (pack_bits + 1)


def _pos_bits(saved_pos: int) -> int:
    if saved_pos < (1 << 7):
        return 8
    return 8 + _len_bits((saved_pos - (1 << 7)) >> 7, _POS_PACK_BITS)


class _Coder:
    """Bit-exact port of tinyuz's TTuzCode emitter."""

    def __init__(self) -> None:
        self.code = bytearray(_DICT_SIZE_BYTES)  # dict size patched in at the end
        self._type_count = 0
        self._types_index = 0
        self.dict_pos_back = 1
        self.have_data_back = False
        self.dict_size_max = 1

    def out_type(self, bit: int) -> None:
        if self._type_count == 0:
            self._types_index = len(self.code)
            self.code.append(0)
        self.code[self._types_index] |= (bit & 1) << self._type_count
        self._type_count = (self._type_count + 1) % 8

    def out_len(self, value: int, pack_bits: int) -> None:
        count = 1
        while value >= (1 << (count * pack_bits)):
            value -= 1 << (count * pack_bits)
            count += 1
        for chunk in reversed(range(count)):
            for bit in range(pack_bits):
                self.out_type((value >> (chunk * pack_bits + bit)) & 1)
            self.out_type(1 if chunk > 0 else 0)

    def out_dict_pos(self, pos: int) -> None:
        big = pos >= (1 << 7)
        if big:
            pos -= 1 << 7
        self.code.append((pos & 0x7F) | (0x80 if big else 0))
        if big:
            self.out_len(pos >> 7, _POS_PACK_BITS)

    def out_ctrl(self, ctrl: int) -> None:
        self.out_type(0)
        self.out_len(ctrl, _LEN_PACK_BITS)
        if self.have_data_back:
            self.out_type(0)
        self.out_dict_pos(0)

    def out_data(self, data: bytes) -> None:
        if len(data) >= _MIN_LITERAL_LINE:
            self.out_ctrl(_CTRL_LITERAL_LINE)
            self.out_len(len(data) - _MIN_LITERAL_LINE, _POS_PACK_BITS)
            self.code += data
        else:
            for byte in data:
                self.out_type(1)
                self.code.append(byte)
        self.have_data_back = True

    def out_match(self, length: int, distance: int) -> None:
        """distance is tinyuz's saved_dict_pos: how far back the copy starts (>= 1)."""
        self.out_type(0)
        self.dict_size_max = max(self.dict_size_max, distance)
        same = self.have_data_back and distance == self.dict_pos_back
        saved_len = length - _MIN_MATCH
        if not same and distance > _BIG_POS_FOR_LEN:
            saved_len -= 1
        self.out_len(saved_len, _LEN_PACK_BITS)
        if self.have_data_back:
            self.out_type(1 if same else 0)
        if not same:
            self.out_dict_pos(distance)
        self.have_data_back = False
        self.dict_pos_back = distance

    def finish(self) -> bytes:
        self.out_ctrl(_CTRL_STREAM_END)
        self._type_count = 0
        self.code[:_DICT_SIZE_BYTES] = self.dict_size_max.to_bytes(
            _DICT_SIZE_BYTES, "little"
        )
        return bytes(self.code)


def compress(data: bytes, *, dict_size: int = DICT_SIZE) -> bytes:
    """Compress with LZ matches inside a dict_size window.

    Picks matches by the cheapest path through the data (an optimal parse, as the
    upstream compressor does), then emits them with the exact tinyuz coder.
    """
    if not data:
        raise ValueError("data cannot be empty")
    if not 1 <= dict_size <= 0xFFFFFFFF:
        raise ValueError("dict_size must be between 1 and 2^32-1")
    n = len(data)
    chains: dict[int, list[int]] = {}
    inf = float("inf")
    price = [inf] * (n + 1)
    price[0] = 0
    step: list[tuple[int, int]] = [(0, 0)] * (
        n + 1
    )  # (length, distance); distance 0 = literal
    # Coder state at the end of the cheapest path to each position: last match distance and
    # whether a literal came after it (then repeating that distance costs one bit).
    rep = [1] * (n + 1)
    after_literal = [False] * (n + 1)
    skip_until = 0
    for pos in range(n):
        here = price[pos]
        if here + 9 < price[pos + 1]:
            price[pos + 1] = here + 9
            step[pos + 1] = (1, 0)
            rep[pos + 1] = rep[pos]
            after_literal[pos + 1] = True
        if pos + 1 < n:
            key = data[pos] | (data[pos + 1] << 8)
            chain = chains.get(key)
            if pos >= skip_until and here != inf and chain:
                limit = min(_MAX_MATCH, n - pos)
                covered = _MIN_MATCH - 1
                longest = 0
                have_data = after_literal[pos]
                last = rep[pos]
                starts = list(reversed(chain[-_MAX_CHAIN:]))
                if (
                    have_data
                    and 0 < last <= pos
                    and pos - last not in chain[-_MAX_CHAIN:]
                ):
                    starts.insert(0, pos - last)
                for start in starts:
                    distance = pos - start
                    if distance > dict_size:
                        break
                    length = 0
                    while length < limit and data[start + length] == data[pos + length]:
                        length += 1
                    longest = max(longest, length)
                    is_rep = have_data and distance == last
                    low = _MIN_MATCH if is_rep else max(covered + 1, _MIN_MATCH)
                    if not is_rep and distance > _BIG_POS_FOR_LEN:
                        low = max(low, _MIN_MATCH + 1)
                    for size in range(low, length + 1):
                        cost = here + _match_bits(size, distance, have_data, last)
                        if cost < price[pos + size]:
                            price[pos + size] = cost
                            step[pos + size] = (size, distance)
                            rep[pos + size] = distance
                            after_literal[pos + size] = False
                    if not is_rep:
                        covered = max(covered, length)
                    if length == limit:
                        break
                if longest >= _NICE_MATCH:
                    skip_until = (
                        pos + longest
                    )  # long run: take it, don't search inside it
            if chain is None:
                chain = chains[key] = []
            chain.append(pos)
            if len(chain) > 2 * _MAX_CHAIN:
                del chain[:-_MAX_CHAIN]
    path: list[tuple[int, int]] = []
    pos = n
    while pos > 0:
        size, distance = step[pos]
        path.append((size, distance))
        pos -= size
    coder = _Coder()
    pos = 0
    literal_start = 0
    for size, distance in reversed(path):
        if distance:
            if pos > literal_start:
                coder.out_data(data[literal_start:pos])
            coder.out_match(size, distance)
            literal_start = pos + size
        pos += size
    if pos > literal_start:
        coder.out_data(data[literal_start:pos])
    return coder.finish()


def _match_bits(length: int, distance: int, have_data: bool, rep: int) -> int:
    same = have_data and distance == rep
    saved_len = length - _MIN_MATCH
    if not same and distance > _BIG_POS_FOR_LEN:
        saved_len -= 1
    bits = 1 + _len_bits(saved_len, _LEN_PACK_BITS) + (1 if have_data else 0)
    if not same:
        bits += _pos_bits(distance)
    return bits


def compress_led_payload(payload: bytes, *, dict_size: int = DICT_SIZE) -> bytes:
    """Compress raw LED RGB frames the way the vendor app does (4 KiB dictionary)."""
    return compress(payload, dict_size=dict_size)


class _Reader:
    def __init__(self, code: bytes) -> None:
        self.code = code
        self.pos = _DICT_SIZE_BYTES
        self.types = 0
        self.type_count = 0

    def byte(self) -> int:
        if self.pos >= len(self.code):
            raise TinyUZError("unexpected end of stream")
        value = self.code[self.pos]
        self.pos += 1
        return value

    def bits(self, count: int) -> int:
        if self.type_count >= count:
            result = self.types
            self.type_count -= count
            self.types >>= count
            return result
        value = self.byte()
        result = self.types | (value << self.type_count)
        count -= self.type_count
        self.type_count = 8 - count
        self.types = value >> count
        return result

    def length(self, read_bits: int) -> int:
        value = 0
        while True:
            low = self.bits(read_bits)
            value = (value << (read_bits - 1)) + (low & ((1 << (read_bits - 1)) - 1))
            if not low & (1 << (read_bits - 1)):
                return value
            value += 1

    def dict_pos(self) -> int:
        value = self.byte()
        if value >= (1 << 7):
            value = ((value & 0x7F) | (self.length(3) << 7)) + (1 << 7)
        return value


def decompress(code: bytes, max_size: int = 1 << 24) -> bytes:
    """Port of tinyuz's tuz_decompress_mem (default configuration)."""
    if len(code) < _DICT_SIZE_BYTES:
        raise TinyUZError("stream too short")
    dict_size = int.from_bytes(code[:_DICT_SIZE_BYTES], "little")
    reader = _Reader(code)
    out = bytearray()
    pos_back = 1
    have_data_back = False
    while True:
        if reader.bits(1) & 1 == 0:
            saved_len = reader.length(2)
            if have_data_back and reader.bits(1) & 1:
                saved_pos = pos_back
            else:
                saved_pos = reader.dict_pos()
                saved_len += 1 if saved_pos > _BIG_POS_FOR_LEN else 0
            have_data_back = False
            if saved_pos:
                if saved_pos > len(out) or saved_pos > dict_size:
                    raise TinyUZError("dictionary position out of range")
                pos_back = saved_pos
                for _ in range(saved_len + _MIN_MATCH):
                    out.append(out[-saved_pos])
            elif saved_len == _CTRL_LITERAL_LINE:
                count = reader.length(3) + _MIN_LITERAL_LINE
                if reader.pos + count > len(code):
                    raise TinyUZError("literal line past the end")
                out += code[reader.pos : reader.pos + count]
                reader.pos += count
                have_data_back = True
            else:
                pos_back = 1
                reader.type_count = 0
                if saved_len == _CTRL_STREAM_END:
                    return bytes(out)
                if saved_len != _CTRL_CLIP_END:
                    raise TinyUZError(f"unknown control code {saved_len}")
        else:
            out.append(reader.byte())
            have_data_back = True
        if len(out) > max_size:
            raise TinyUZError("output larger than expected")


def generate_rainbow_frames(
    led_count: int,
    *,
    frame_count: int = 24,
    saturation: float = 1.0,
    value: float = 1.0,
) -> bytes:
    if led_count <= 0:
        raise ValueError("led_count must be positive")
    if frame_count <= 0:
        raise ValueError("frame_count must be positive")
    frames: list[int] = []
    for frame in range(frame_count):
        offset = frame / frame_count
        for index in range(led_count):
            hue = (index / max(1, led_count) + offset) % 1.0
            r, g, b = _hsv_to_rgb(hue, saturation, value)
            frames.extend((r, g, b))
    return bytes(frames)


def _hsv_to_rgb(h: float, s: float, v: float) -> Sequence[int]:
    h = h % 1.0
    s = max(0.0, min(1.0, s))
    v = max(0.0, min(1.0, v))
    i = int(h * 6.0)
    f = h * 6.0 - i
    p = v * (1.0 - s)
    q = v * (1.0 - f * s)
    t = v * (1.0 - (1.0 - f) * s)
    i = i % 6
    if i == 0:
        r, g, b = v, t, p
    elif i == 1:
        r, g, b = q, v, p
    elif i == 2:
        r, g, b = p, v, t
    elif i == 3:
        r, g, b = p, q, v
    elif i == 4:
        r, g, b = t, p, v
    else:
        r, g, b = v, p, q
    return int(r * 255) & 0xFF, int(g * 255) & 0xFF, int(b * 255) & 0xFF
