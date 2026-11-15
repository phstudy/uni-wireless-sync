"""Pre-rendered TL effects (frames rendered by the vendor app)."""

import pytest

from uwscli import tl_effects
from uwscli.tl_effects import PRERENDERED, TLEffectGenerator, TLEffects


@pytest.mark.parametrize("effect", sorted(PRERENDERED, key=lambda e: e.value))
def test_every_combination_is_present(effect):
    table = tl_effects._load_prerendered(effect)
    assert len(table) == 2 * 4 * 2 * 5
    for (side, fans, _direction, level), frames in table.items():
        for frame in frames:
            assert [len(c) for c in frame] == [fans * 26] * 3
            lit = [led for c in frame for led, v in enumerate(c) if v]
            # each side lights only its own 13 LEDs of every fan
            assert all((led % 26 < 13) == (side == 0) for led in lit)
        if level > 0:
            assert frames, (side, fans, level)


def test_twenty_effects_are_prerendered_and_nine_built_in():
    assert len(PRERENDERED) == 20 and len(TLEffects) == 29


def test_brightness_snaps_to_the_app_levels():
    gen = TLEffectGenerator()
    assert gen.generate(TLEffects.WAVE, 0, 2, 200, 1) == gen.generate(
        TLEffects.WAVE, 0, 2, 192, 1
    )
    assert gen.generate(TLEffects.WAVE, 0, 2, 255, 1) != gen.generate(
        TLEffects.WAVE, 0, 2, 128, 1
    )


def test_brightness_zero_is_dark():
    frames = TLEffectGenerator().generate(TLEffects.MIXING, 1, 3, 0, 0)
    assert frames and all(v == 0 for f in frames for c in f for v in c)


def test_custom_colours_are_refused_for_prerendered_effects():
    with pytest.raises(ValueError, match="default colours"):
        TLEffectGenerator([[1, 2, 3]]).generate(TLEffects.COLLIDE, 0, 1, 255, 0)
    TLEffectGenerator([[1, 2, 3]]).generate(TLEffects.METEOR, 0, 1, 255, 0)


def test_default_colours_given_explicitly_are_accepted():
    TLEffectGenerator(tl_effects.EFFECT_DEFAULT_COLOURS[TLEffects.COLLIDE]).generate(
        TLEffects.COLLIDE, 0, 1, 255, 0
    )


def test_speed_intervals():
    assert tl_effects.effect_interval(TLEffects.WAVE, 3) == 55
    assert tl_effects.effect_interval(TLEffects.WAVE, 1) == 77
    assert tl_effects.effect_interval(TLEffects.COLLIDE, 5) == 48


def test_bright_colours_are_dimmed_like_the_app():
    assert tl_effects.clamp_colour([255, 255, 255]) == [195, 195, 195]
    assert tl_effects.clamp_colour([255, 255, 0]) == [255, 255, 0]


def test_cli_speed_and_colours_reach_the_effect(monkeypatch):
    from uwscli import cli, wireless

    calls = []

    class Tx:
        def __enter__(self):
            return self

        def __exit__(self, *exc):
            return False

        def set_led_effect(self, mac, effect, **kwargs):
            calls.append((effect, kwargs))

    monkeypatch.setattr(wireless, "WirelessTransceiver", lambda *a, **k: Tx())
    cli.main(
        [
            "fan",
            "set-led",
            "--mac",
            "aa:bb:cc:dd:ee:01",
            "--mode",
            "effect",
            "--effect",
            "meteor",
            "--speed",
            "1",
            "--effect-colors",
            "1,2,3;4,5,6",
        ]
    )
    effect, kwargs = calls[0]
    assert effect is TLEffects.METEOR and kwargs["interval_ms"] == 77
    assert kwargs["colours"] == [[1, 2, 3], [4, 5, 6]]


def test_every_effect_has_the_app_default_colours():
    assert set(tl_effects.EFFECT_DEFAULT_COLOURS) == set(TLEffects)
    assert tl_effects.EFFECT_DEFAULT_COLOURS[TLEffects.STATIC_COLOR][0] == [
        0xAA,
        0x00,
        0xFF,
    ]


def test_fewer_colours_keep_the_rest_of_the_app_table():
    gen = TLEffectGenerator([[1, 2, 3]])
    gen._set_colours(TLEffects.METEOR)
    assert gen._colours[0][0] == [1, 2, 3] and gen._colours[1][0] == [1, 2, 3]
    assert gen._colours[0][1] == tl_effects.SLV3_USER_COLOUR[0][1]
    assert gen._colours[1][1] == tl_effects.SLV3_USER_COLOUR[1][1]


def test_flip_swaps_front_and_behind_of_every_fan():
    frame = [[list(range(52)), [0] * 52, [0] * 52]]
    flipped = tl_effects.flip_sides(frame)[0][0]
    assert flipped[:13] == list(range(13, 26)) and flipped[13:26] == list(range(13))
    assert flipped[26:39] == list(range(39, 52))
    assert tl_effects.flip_sides(tl_effects.flip_sides(frame)) == frame
