"""tinyuz encoder/decoder tests.

tests/data/vendor_*.yuz were produced by the vendor app's own encoder from the inputs
built by _vendor_inputs(); they pin the stream format the fans decode.
"""

import colorsys
import random
from pathlib import Path

import pytest

from uwscli import tinyuz
from uwscli.tl_effects import TLEffectGenerator, TLEffects

DATA = Path(__file__).parent / "data"


def _vendor_inputs():
    static = bytes([255, 0, 0] * 26 * 6)
    rainbow = bytearray()
    for frame in range(24):
        for led in range(156):
            rgb = colorsys.hsv_to_rgb((led / 156 + frame / 24) % 1, 1, 1)
            rainbow += bytes(int(x * 255) for x in rgb)
    return {"static": static, "rainbow": bytes(rainbow)}


@pytest.mark.parametrize("name", ["static", "rainbow"])
def test_decodes_vendor_streams(name):
    assert (
        tinyuz.decompress((DATA / f"vendor_{name}.yuz").read_bytes())
        == _vendor_inputs()[name]
    )


def test_solid_colour_is_byte_identical_to_vendor():
    assert (
        tinyuz.compress(_vendor_inputs()["static"])
        == (DATA / "vendor_static.yuz").read_bytes()
    )


def test_rainbow_compresses_close_to_vendor():
    ours = len(tinyuz.compress(_vendor_inputs()["rainbow"]))
    assert ours <= len((DATA / "vendor_rainbow.yuz").read_bytes()) * 1.1


def test_header_is_the_largest_distance_used():
    code = tinyuz.compress(bytes([1, 2, 3] * 100))
    assert int.from_bytes(code[:4], "little") == 3
    code = tinyuz.compress(bytes(range(200)))
    assert int.from_bytes(code[:4], "little") == 1


def _effect_bytes(effect, fans):
    buf = bytearray()
    for frame in TLEffectGenerator().generate(effect, 0, fans, 255, 1):
        for led in range(len(frame[0])):
            buf += bytes((frame[0][led], frame[1][led], frame[2][led]))
    return bytes(buf)


@pytest.mark.parametrize("effect", list(TLEffects)[:12])
def test_roundtrip_tl_effects(effect):
    data = _effect_bytes(effect, 3)
    if not data:
        pytest.skip("effect produced no frames")
    code = tinyuz.compress(data)
    assert tinyuz.decompress(code) == data
    assert int.from_bytes(code[:4], "little") <= tinyuz.DICT_SIZE


@pytest.mark.parametrize("seed", range(8))
def test_roundtrip_random(seed):
    rnd = random.Random(seed)
    alphabet = [rnd.randrange(256) for _ in range(rnd.randint(1, 6))]
    data = bytes(rnd.choice(alphabet) for _ in range(rnd.randint(1, 6000)))
    assert tinyuz.decompress(tinyuz.compress(data)) == data
    noise = bytes(rnd.randrange(256) for _ in range(rnd.randint(1, 3000)))
    assert tinyuz.decompress(tinyuz.compress(noise)) == noise


def test_small_dictionary_limits_distance():
    data = bytes(range(50)) * 4
    code = tinyuz.compress(data, dict_size=40)
    assert tinyuz.decompress(code) == data
    assert int.from_bytes(code[:4], "little") <= 40


def test_empty_payload_rejected():
    with pytest.raises(ValueError):
        tinyuz.compress_led_payload(b"")


def test_generate_rainbow_frames_length():
    assert len(tinyuz.generate_rainbow_frames(10, frame_count=5)) == 10 * 5 * 3


def test_builtin_effects_match_the_vendor_app():
    """Hashes of the frames the vendor app renders for its nine built-in TL effects (every
    side, fan count, direction), with its default colours at several brightness levels and
    with a custom colour set."""
    import hashlib
    import json

    fixture = json.loads((DATA / "tl_builtin_effects.json").read_text())
    generators = {
        name: TLEffectGenerator(colours) for name, colours in fixture["colours"].items()
    }
    for key, digest in fixture["hashes"].items():
        name, mode, tb, fans, direction, bright = key.split("/")
        frames = generators[name].generate(
            TLEffects(int(mode)), int(tb), int(fans), int(bright), int(direction)
        )
        data = bytes(v for frame in frames for channel in frame for v in channel)
        assert hashlib.sha256(data).hexdigest()[:16] == digest, key


def _side(frames, fans, side):
    leds = fans * 26
    return [
        [
            [
                (
                    ((f * 7 + c * 13 + led * 3 + side * 50) % 256)
                    if ((led % 26 < 13) == (side == 0))
                    else 0
                )
                for led in range(leds)
            ]
            for c in range(3)
        ]
        for f in range(frames)
    ]


def test_front_and_behind_merge_like_the_vendor_app():
    """Hashes of the vendor app's merge of a front and a behind effect (R,G,B per LED)."""
    import hashlib
    import json

    from uwscli.tl_effects import merge_sides

    for key, digest in json.loads((DATA / "tl_merge.json").read_text()).items():
        fans, front, behind, interval = map(int, key.split("/"))
        merged = merge_sides(_side(front, fans, 0), _side(behind, fans, 1), interval)
        data = bytes(
            merged[f][c][led]
            for f in range(len(merged))
            for led in range(fans * 26)
            for c in range(3)
        )
        assert hashlib.sha256(data).hexdigest()[:16] == digest, key
