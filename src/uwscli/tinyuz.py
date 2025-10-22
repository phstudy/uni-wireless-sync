"""LED payload helpers with a TinyUZ-compatible encoder implemented in Python."""

from __future__ import annotations

from dataclasses import dataclass
from typing import List, Sequence

__all__ = [
    "TinyUZError",
    "compress_led_payload",
    "generate_rainbow_frames",
]


class TinyUZError(RuntimeError):
    """Raised when TinyUZ compression fails."""


_DICT_SIZE = 4096
_DICT_SIZE_BYTES = 4  # Matches default tinyuz build configuration.
_CTRL_STREAM_END = 3
_CODE_TYPE_DICT = 0
_CODE_TYPE_DATA = 1


def compress_led_payload(payload: bytes, *, dict_size: int = _DICT_SIZE) -> bytes:
    """Compress raw LED frame data using a literal-only TinyUZ encoder.

    Args:
        payload: Raw LED RGB data laid out frame-by-frame.
        dict_size: Dictionary size advertised in the output stream (defaults to 4 KiB).

    Returns:
        Bytes encoded in the TinyUZ format.

    Raises:
        ValueError: If the payload is empty or dict_size is invalid.
    """

    if not payload:
        raise ValueError("payload cannot be empty")
    if dict_size <= 0 or dict_size >= (1 << (8 * _DICT_SIZE_BYTES)):
        raise ValueError("dict_size must be between 1 and 2^32-1")

    writer = _TinyUZLiteralEncoder(dict_size=dict_size)
    writer.write_literal(payload)
    writer.finish()
    return writer.to_bytes()


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
    frames: List[int] = []
    for frame in range(frame_count):
        offset = frame / frame_count
        for index in range(led_count):
            hue = (index / max(1, led_count) + offset) % 1.0
            r, g, b = _hsv_to_rgb(hue, saturation, value)
            frames.extend((r, g, b))
    return bytes(frames)


@dataclass
class _BitStreamState:
    code: List[int]
    type_count: int = 0
    types_index: int | None = None
    dict_pos_back: int = 1
    is_have_data_back: bool = False


class _TinyUZLiteralEncoder:
    """Minimal TinyUZ encoder that emits literal bytes followed by stream end."""

    def __init__(self, *, dict_size: int) -> None:
        self._dict_size = dict_size
        self._state = _BitStreamState(code=[])

        # Reserve space for the dictionary size header.
        for shift in range(_DICT_SIZE_BYTES):
            self._state.code.append((dict_size >> (8 * shift)) & 0xFF)

    def write_literal(self, data: bytes) -> None:
        for byte in data:
            self._out_type(_CODE_TYPE_DATA)
            self._state.code.append(byte)
            self._state.is_have_data_back = True

    def finish(self) -> None:
        self._out_ctrl(_CTRL_STREAM_END)
        self._reset_types()

    def to_bytes(self) -> bytes:
        return bytes(self._state.code)

    # --- Encoding helpers ---

    def _out_type(self, bit: int) -> None:
        if self._state.type_count == 0:
            self._state.types_index = len(self._state.code)
            self._state.code.append(0)
        index = self._state.types_index
        if index is None:
            raise TinyUZError("Type index not initialised")
        self._state.code[index] |= (bit & 1) << self._state.type_count
        self._state.type_count = (self._state.type_count + 1) % 8
        if self._state.type_count == 0:
            self._state.types_index = None

    def _out_len(self, value: int, pack_bit: int) -> None:
        if value < 0:
            raise TinyUZError("Length cannot be negative")
        count, v = self._compute_length_chunks(value, pack_bit)
        for idx in reversed(range(count)):
            for bit_index in range(pack_bit):
                shift = idx * pack_bit + bit_index
                self._out_type((v >> shift) & 1)
            self._out_type(1 if idx > 0 else 0)

    @staticmethod
    def _compute_length_chunks(value: int, pack_bit: int) -> tuple[int, int]:
        count = 1
        v = value
        original = value
        while True:
            threshold = 1 << (count * pack_bit)
            if v < threshold:
                break
            v -= threshold
            count += 1
        dec = original - v
        adjusted = original - dec
        return count, adjusted

    def _out_ctrl(self, ctrl: int) -> None:
        self._out_type(_CODE_TYPE_DICT)
        self._out_len(ctrl, pack_bit=1)
        if self._state.is_have_data_back:
            self._out_type(0)
        self._out_dict_pos(0)
        self._state.is_have_data_back = False
        self._state.dict_pos_back = 1

    def _out_dict_pos(self, pos: int) -> None:
        if pos < 0:
            raise TinyUZError("Dictionary position cannot be negative")
        if pos < 0x80:
            self._state.code.append(pos & 0x7F)
        else:
            raise TinyUZError(
                "Dictionary positions >=128 are not supported in literal encoder"
            )

    def _reset_types(self) -> None:
        self._state.type_count = 0
        self._state.types_index = None
        self._state.dict_pos_back = 1
        self._state.is_have_data_back = False


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
