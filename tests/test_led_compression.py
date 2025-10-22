import os
from typing import Tuple

import pytest

from uwscli.tinyuz import (
    _CTRL_STREAM_END,
    compress_led_payload,
    generate_rainbow_frames,
)


def _decode_literal_stream(encoded: bytes) -> Tuple[int, bytes]:
    dict_size = int.from_bytes(encoded[:4], "little")
    data = encoded[4:]
    pos = 0
    type_bits = 0
    bits_left = 0

    def read_byte() -> int:
        nonlocal pos
        if pos >= len(data):
            raise AssertionError("Unexpected end of stream while reading byte")
        value = data[pos]
        pos += 1
        return value

    def read_type_bit() -> int:
        nonlocal type_bits, bits_left
        if bits_left == 0:
            type_bits = read_byte()
            bits_left = 8
        bit = type_bits & 1
        type_bits >>= 1
        bits_left -= 1
        return bit

    def read_len(pack_bit: int) -> int:
        value = 0
        while True:
            low = 0
            for i in range(pack_bit):
                low |= read_type_bit() << i
            flag = read_type_bit()
            value = (value << pack_bit) + low
            if flag == 0:
                return value
            value += 1

    output = bytearray()
    is_have_data_back = False
    while True:
        code_type = read_type_bit()
        if code_type == 1:
            output.append(read_byte())
            is_have_data_back = True
            continue

        saved_len = read_len(1)
        if is_have_data_back:
            reuse_flag = read_type_bit()
            assert reuse_flag == 0, "literal encoder must not emit reuse flag"
        dict_pos = read_byte()
        assert dict_pos == 0, "literal encoder must emit ctrl with dict_pos=0"
        if saved_len == _CTRL_STREAM_END:
            break
        raise AssertionError(f"Unsupported control code {saved_len}")

    return dict_size, bytes(output)


def test_compress_led_payload_roundtrip():
    payload = os.urandom(64)
    encoded = compress_led_payload(payload)
    dict_size, decoded = _decode_literal_stream(encoded)
    assert dict_size == 4096
    assert decoded == payload


def test_compress_led_payload_dict_size_override():
    payload = b"\x01\x02\x03"
    encoded = compress_led_payload(payload, dict_size=255)
    dict_size, decoded = _decode_literal_stream(encoded)
    assert dict_size == 255
    assert decoded == payload


def test_compress_led_payload_empty_payload():
    with pytest.raises(ValueError):
        compress_led_payload(b"")


def test_generate_rainbow_frames_length():
    led_count = 8
    frame_count = 6
    frames = generate_rainbow_frames(led_count, frame_count=frame_count)
    assert len(frames) == led_count * frame_count * 3
