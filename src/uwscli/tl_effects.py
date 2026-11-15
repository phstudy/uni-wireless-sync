from __future__ import annotations

import importlib.resources as pkg_resources
import json
import lzma
import struct
import zlib
from enum import Enum, unique
from typing import Any


@unique
class TLEffects(Enum):
    RAINBOW = 1
    RAINBOW_MORPH = 2
    STATIC_COLOR = 3
    BREATHING = 4
    RUNWAY = 5
    METEOR = 6
    COLOR_CYCLE = 7
    STAGGERED = 8
    TIDE = 9
    MIXING = 10
    VOICE = 11
    DOOR = 12
    RENDER = 13
    RIPPLE = 14
    REFLECT = 15
    TAIL_CHASING = 16
    PAINT = 17
    PING_PONG = 18
    STACK = 19
    COVER_CYCLE = 20
    WAVE = 21
    RACING = 22
    LOTTERY = 23
    INTERTWINE = 24
    METEOR_SHOWER = 25
    COLLIDE = 26
    ELECTRIC_CURRENT = 27
    KALEIDOSCOPE = 28
    TWINKLE = 29


SLV3_USER_COLOUR: list[list[list[int]]] = [
    [[255, 0, 0], [0, 0, 255], [0, 255, 0], [255, 255, 0]],
    [[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 0]],
    [[255, 0, 0], [255, 255, 0], [255, 0, 255], [255, 255, 0]],
    [[255, 0, 255], [0, 0, 255], [0, 255, 0], [255, 255, 0]],
]

RAINBOW_TABLES: dict[int, list[list[int]]] = {
    1: [
        [255, 204, 153, 102, 51, 0, 0, 0, 0, 0, 0, 51, 102, 153, 204],
        [0, 51, 102, 153, 204, 255, 204, 153, 102, 51, 0, 0, 0, 0, 0],
        [0, 0, 0, 0, 0, 0, 51, 102, 153, 204, 255, 204, 153, 102, 51],
    ],
    2: [
        [
            255,
            226,
            197,
            168,
            139,
            110,
            81,
            52,
            23,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            23,
            52,
            81,
            110,
            139,
            168,
            197,
            226,
        ],
        [
            0,
            23,
            52,
            81,
            110,
            139,
            168,
            197,
            226,
            255,
            226,
            197,
            168,
            139,
            110,
            81,
            52,
            23,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            23,
            52,
            81,
            110,
            139,
            168,
            197,
            226,
            255,
            226,
            197,
            168,
            139,
            110,
            81,
            52,
            23,
        ],
    ],
    3: [
        [
            255,
            235,
            215,
            195,
            175,
            155,
            135,
            115,
            95,
            75,
            55,
            35,
            15,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            15,
            35,
            55,
            75,
            95,
            115,
            135,
            155,
            175,
            195,
            215,
            235,
        ],
        [
            0,
            15,
            35,
            55,
            75,
            95,
            115,
            135,
            155,
            175,
            195,
            215,
            235,
            255,
            235,
            215,
            195,
            175,
            155,
            135,
            115,
            95,
            75,
            55,
            35,
            15,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            15,
            35,
            55,
            75,
            95,
            115,
            135,
            155,
            175,
            195,
            215,
            235,
            255,
            235,
            215,
            195,
            175,
            155,
            135,
            115,
            95,
            75,
            55,
            35,
            15,
        ],
    ],
    4: [
        [
            255,
            241,
            227,
            213,
            199,
            185,
            171,
            157,
            143,
            129,
            115,
            101,
            87,
            73,
            59,
            45,
            31,
            17,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            17,
            31,
            45,
            59,
            73,
            87,
            101,
            115,
            129,
            143,
            157,
            171,
            185,
            199,
            213,
            227,
            241,
        ],
        [
            0,
            17,
            31,
            45,
            59,
            73,
            87,
            101,
            115,
            129,
            143,
            157,
            171,
            185,
            199,
            213,
            227,
            241,
            255,
            241,
            227,
            213,
            199,
            185,
            171,
            157,
            143,
            129,
            115,
            101,
            87,
            73,
            59,
            45,
            31,
            17,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
        ],
        [
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            0,
            17,
            31,
            45,
            59,
            73,
            87,
            101,
            115,
            129,
            143,
            157,
            171,
            185,
            199,
            213,
            227,
            241,
            255,
            241,
            227,
            213,
            199,
            185,
            171,
            157,
            143,
            129,
            115,
            101,
            87,
            73,
            59,
            45,
            31,
            17,
        ],
    ],
}

METEOR_WEIGHTS: list[list[int]] = [
    [32, 255, 0, 0, 0, 0, 0, 0],
    [16, 64, 128, 255, 0, 0, 0, 0],
    [8, 16, 32, 64, 128, 255, 0, 0],
    [6, 10, 16, 32, 64, 96, 168, 255],
]

COLOR_CYCLE_SOLID_LENGTHS: list[int] = [1, 2, 5, 8]
COLOR_CYCLE_GAP_LENGTHS: list[int] = [3, 6, 8, 9]

TWINKLE_PACKAGE = "uwscli.data"
TWINKLE_RESOURCE = "twinkle.bin"

_TWINKLE_TABLES_CACHE: dict[str, Any] | None = None


def _load_twinkle_tables() -> dict[str, Any]:
    global _TWINKLE_TABLES_CACHE
    if _TWINKLE_TABLES_CACHE is None:
        with (
            pkg_resources.files(TWINKLE_PACKAGE)
            .joinpath(TWINKLE_RESOURCE)
            .open("rb") as handle
        ):
            payload = zlib.decompress(handle.read())
        _TWINKLE_TABLES_CACHE = json.loads(payload.decode("ascii"))
    return _TWINKLE_TABLES_CACHE


def _hex(*values: str) -> list[list[int]]:
    return [[int(v[i : i + 2], 16) for i in (0, 2, 4)] for v in values]


_R, _B, _G, _Y = "FF0000", "0000FF", "008000", "FFFF00"
# The colours the app's lighting page starts each effect with (empty: the effect has none).
EFFECT_DEFAULT_COLOURS: dict[TLEffects, list[list[int]]] = {
    TLEffects.RAINBOW: [],
    TLEffects.RAINBOW_MORPH: [],
    TLEffects.STATIC_COLOR: _hex("AA00FF", "00D7FF", "00FF00", "FFD800"),
    TLEffects.BREATHING: _hex("AA00FF", "00D7FF", "00FF00", "FFD800"),
    TLEffects.RUNWAY: _hex("FFFFFF", "FF0096"),
    TLEffects.METEOR: _hex("FF0096", "00D7FF", "00FF00", "FFD700"),
    TLEffects.COLOR_CYCLE: _hex("FFD700", "00FF00", "00D7FF"),
    TLEffects.STAGGERED: _hex("00D7FF", "FF0096"),
    TLEffects.TIDE: _hex("FF0096", "0000FF"),
    TLEffects.MIXING: _hex(_R, _B),
    TLEffects.VOICE: [],
    TLEffects.DOOR: _hex(_R, _B, _G, _Y),
    TLEffects.RENDER: _hex("FF0096", "0000FF", "00FF00", "FFF026"),
    TLEffects.RIPPLE: _hex(_R, _B, _G, _Y),
    TLEffects.REFLECT: _hex(_R, _B, _G, _Y),
    TLEffects.TAIL_CHASING: _hex(_R, _B),
    TLEffects.PAINT: _hex(_R, _B, _G, _Y),
    TLEffects.PING_PONG: _hex(_R, _B, _G, _Y),
    TLEffects.STACK: _hex(_R, _B, "00FF00", _Y),
    TLEffects.COVER_CYCLE: _hex(_R, _B, _G),
    TLEffects.WAVE: _hex(_R, _B, _G, _Y),
    TLEffects.RACING: _hex(_R, _B),
    TLEffects.LOTTERY: _hex(_R, _B),
    TLEffects.INTERTWINE: _hex(_R, _B),
    TLEffects.METEOR_SHOWER: _hex("FF0096", "00D7FF", "00FF00", "FFD700"),
    TLEffects.COLLIDE: _hex(_R, _B, _G, _Y),
    TLEffects.ELECTRIC_CURRENT: _hex(_R, _B, _G, _Y),
    TLEffects.KALEIDOSCOPE: [],
    TLEffects.TWINKLE: [],
}
# The app's default speed and brightness on its lighting page (75 and 100 of 100).
DEFAULT_SPEED = 4

# The app's brightness levels (1-5).
BRIGHTNESS_LEVELS = (0, 64, 128, 192, 255)

# Effects shipped as frames rendered by the app (default colours, every side, fan count,
# direction and brightness level). Voice, meteor shower and kaleidoscope are random in the
# app; the frames hold one rendering of each.
PRERENDERED = frozenset(
    {
        TLEffects.STAGGERED,
        TLEffects.TIDE,
        TLEffects.MIXING,
        TLEffects.VOICE,
        TLEffects.DOOR,
        TLEffects.RENDER,
        TLEffects.RIPPLE,
        TLEffects.REFLECT,
        TLEffects.TAIL_CHASING,
        TLEffects.PAINT,
        TLEffects.PING_PONG,
        TLEffects.COVER_CYCLE,
        TLEffects.WAVE,
        TLEffects.RACING,
        TLEffects.LOTTERY,
        TLEffects.INTERTWINE,
        TLEffects.METEOR_SHOWER,
        TLEffects.COLLIDE,
        TLEffects.ELECTRIC_CURRENT,
        TLEffects.KALEIDOSCOPE,
    }
)
FRAMES_PACKAGE = "uwscli.data.tl_frames"

Frames = list[list[list[int]]]
_FRAMES_CACHE: dict[TLEffects, dict[tuple[int, int, int, int], Frames]] = {}


def _load_prerendered(effect: TLEffects) -> dict[tuple[int, int, int, int], Frames]:
    """(side, fans, direction, brightness level) -> frames, from data/tl_frames/<effect>.xz."""
    cached = _FRAMES_CACHE.get(effect)
    if cached is not None:
        return cached
    resource = pkg_resources.files(FRAMES_PACKAGE).joinpath(f"{effect.name.lower()}.xz")
    raw = lzma.decompress(resource.read_bytes())
    if raw[:4] != b"TLF1":
        raise ValueError(f"bad frame data for {effect.name}")
    table: dict[tuple[int, int, int, int], Frames] = {}
    pos = 4
    while pos < len(raw):
        side, fans, direction, level, count = struct.unpack_from("<BBBBH", raw, pos)
        pos += 6
        leds = fans * TLEffectGenerator.LEDS_PER_FAN
        frames: Frames = []
        for _ in range(count):
            frames.append(
                [list(raw[pos + c * leds : pos + (c + 1) * leds]) for c in range(3)]
            )
            pos += 3 * leds
        table[(side, fans, direction, level)] = frames
    _FRAMES_CACHE[effect] = table
    return table


def brightness_level(brightness: int) -> int:
    """Index of the app brightness level closest to a 0-255 brightness."""
    return min(
        range(len(BRIGHTNESS_LEVELS)),
        key=lambda i: abs(BRIGHTNESS_LEVELS[i] - brightness),
    )


def effect_interval(effect: TLEffects, speed: int) -> int:
    """Frame interval in ms the app uses: speed 1-5 is its level L1-L5 (7..3) times 11 ms
    (16 ms for collide)."""
    if not 1 <= speed <= 5:
        raise ValueError("speed must be 1-5")
    base = 16 if effect is TLEffects.COLLIDE else 11
    return (8 - speed) * base


def flip_sides(frames: Frames) -> Frames:
    """The app's "UpDownSwap": swap the front and behind halves of every fan."""
    half = TLEffectGenerator.HALF_RING
    flipped: Frames = []
    for frame in frames:
        channels = []
        for channel in frame:
            row = list(channel)
            for start in range(0, len(row), 2 * half):
                row[start : start + half], row[start + half : start + 2 * half] = (
                    channel[start + half : start + 2 * half],
                    channel[start : start + half],
                )
            channels.append(row)
        flipped.append(channels)
    return flipped


def merge_sides(front: Frames, behind: Frames, interval_ms: int) -> Frames:
    """Combine a front and a behind effect as the app does.

    The longer effect sets the frame count; the shorter one is repeated whole as many
    times as fits (when it is at most half as long) and then stretched in time over it.
    """
    if not front or not behind:
        return [[list(c) for c in f] for f in (front or behind)]
    leds = len(front[0][0])
    interval = int(interval_ms)
    # The longer effect is the base (the front one when they are equally long).
    if len(behind) > len(front):
        base, other, other_half = (
            behind,
            front,
            0,
        )  # copy the front half from the shorter effect
    else:
        base, other, other_half = front, behind, 1  # copy the behind half
    longest, shortest = len(base), len(other)
    if longest // 2 >= shortest:
        repeats = longest // shortest
        other = [other[i % shortest] for i in range(repeats * shortest)]
        shortest = repeats * shortest
    step = max(1, interval * longest // shortest)
    merged: Frames = [[list(c) for c in frame] for frame in base]
    for index in range(longest):
        source = min(int(index * interval / step), shortest - 1)
        for fan_start in range(0, leds, TLEffectGenerator.LEDS_PER_FAN):
            start = fan_start + other_half * TLEffectGenerator.HALF_RING
            for led in range(start, start + TLEffectGenerator.HALF_RING):
                for channel in range(3):
                    merged[index][channel][led] = other[source][channel][led]
    return merged


def clamp_colour(colour: list[int]) -> list[int]:
    """The app scales a colour by 0.95 until its channels sum to at most 600."""
    r, g, b = colour
    while r + g + b > 600:
        r, g, b = int(r * 0.95), int(g * 0.95), int(b * 0.95)
    return [r, g, b]


class TLEffectGenerator:
    LEDS_PER_FAN = 26
    HALF_RING = 13

    def __init__(self, colours: list[list[int]] | None = None) -> None:
        """colours: the effect's colours as on the app's lighting page (None: the app's
        defaults for each effect). As in the app, colour j replaces slot j of its built-in
        colour table for both sides; slots without a colour keep the table's entries.
        Pre-rendered effects exist only with their default colours."""
        self._twinkle_cache = None
        self._chosen = None if colours is None else [list(c) for c in colours]
        self._colours: list[list[list[int]]] = []

    def _colours_for(self, effect: TLEffects) -> list[list[int]]:
        chosen = (
            EFFECT_DEFAULT_COLOURS[effect] if self._chosen is None else self._chosen
        )
        return [clamp_colour(c) for c in chosen]

    def _set_colours(self, effect: TLEffects) -> None:
        table = [[list(c) for c in row] for row in SLV3_USER_COLOUR]
        for slot, colour in enumerate(self._colours_for(effect)[:4]):
            table[0][slot] = list(colour)
            table[1][slot] = list(colour)
        self._colours = table

    def _prerendered(
        self, effect: TLEffects, tb: int, fans: int, bright: int, direction: int
    ) -> Frames:
        if self._colours_for(effect) != [
            clamp_colour(c) for c in EFFECT_DEFAULT_COLOURS[effect]
        ]:
            raise ValueError(
                f"{effect.name.lower()} is available only with the default colours"
            )
        frames = _load_prerendered(effect)[
            (tb, fans, direction, brightness_level(bright))
        ]
        if not frames:  # the app cannot render it at brightness 0: all LEDs off
            return [self._blank_frame(fans)]
        return [[list(c) for c in f] for f in frames]

    def generate(
        self,
        effect: TLEffects,
        tb: int,
        fan_count: int,
        brightness: int,
        direction: int,
    ) -> list[list[list[int]]]:
        tb = 0 if tb >= 2 else tb
        fan_count = self._normalize_fans(fan_count)
        brightness = max(0, min(255, int(brightness)))
        direction = 0 if direction > 1 else max(0, int(direction))
        self._set_colours(effect)

        handlers = {
            TLEffects.RAINBOW: lambda: self._rainbow(
                tb, fan_count, brightness, direction
            ),
            TLEffects.RAINBOW_MORPH: lambda: self._rainbow_morph(
                tb, fan_count, brightness
            ),
            TLEffects.STATIC_COLOR: lambda: self._static_color_quadrants(
                tb, fan_count, brightness
            ),
            TLEffects.BREATHING: lambda: self._breathing(tb, fan_count, brightness),
            TLEffects.RUNWAY: lambda: self._runway(tb, fan_count, brightness),
            TLEffects.METEOR: lambda: self._meteor(
                tb, fan_count, brightness, direction
            ),
            TLEffects.COLOR_CYCLE: lambda: self._color_cycle(
                tb, fan_count, brightness, direction
            ),
            TLEffects.STACK: lambda: self._stack(tb, fan_count, brightness, direction),
            TLEffects.TWINKLE: lambda: self._twinkle(tb, fan_count, brightness),
        }

        if effect in PRERENDERED:
            return self._prerendered(effect, tb, fan_count, brightness, direction)
        try:
            return handlers[effect]()
        except KeyError as exc:
            raise NotImplementedError(
                f"{effect.name} generator is not defined in the original TLMode set."
            ) from exc

    def _rainbow(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> list[list[list[int]]]:
        table = RAINBOW_TABLES[fans]
        table_len = len(table[0])
        frames = []
        num = fans * self.HALF_RING
        for offset in range(num):
            ring = [[0] * num for _ in range(3)]
            idx = offset
            for j in range(num):
                out = num - j - 1 if direction == 0 else j
                ring[0][out] = (table[0][idx] * bright) >> 8
                ring[1][out] = (table[1][idx] * bright) >> 8
                ring[2][out] = (table[2][idx] * bright) >> 8
                idx = (idx + 1) % table_len
            frame = self._blank_frame(fans)
            for fan in range(fans):
                start = fan * self.HALF_RING
                self._fill_half(frame, tb, fan, ring, start)
            frames.append(frame)
        return frames

    def _rainbow_morph(self, tb: int, fans: int, bright: int) -> list[list[list[int]]]:
        num_leds = fans * self.LEDS_PER_FAN
        red, green, blue = 255, 0, 0
        frames = []
        for step in range(255):
            ring = [
                [(red * bright) >> 8] * num_leds,
                [(green * bright) >> 8] * num_leds,
                [(blue * bright) >> 8] * num_leds,
            ]
            frames.append(self._project_half(tb, fans, ring))
            if step < 85:
                red -= 3
                green += 3
                blue = 0
            elif step < 170:
                red = 0
                green -= 3
                blue += 3
            else:
                red += 3
                green = 0
                blue -= 3
        return [frames[i * 2] for i in range(len(frames) // 2)]

    def _static_color_quadrants(
        self, tb: int, fans: int, bright: int
    ) -> list[list[list[int]]]:
        ring = [[0] * (fans * self.HALF_RING) for _ in range(3)]
        for block in range(min(fans, len(self._colours[tb]))):  # one colour per fan
            colour = self._colours[tb][block]
            for idx in range(block * self.HALF_RING, (block + 1) * self.HALF_RING):
                ring[0][idx] = (colour[0] * bright) >> 8
                ring[1][idx] = (colour[1] * bright) >> 8
                ring[2][idx] = (colour[2] * bright) >> 8
        frame = self._project_half(tb, fans, ring)
        return [frame for _ in range(30)]

    def _breathing(self, tb: int, fans: int, bright: int) -> list[list[list[int]]]:
        num = fans * self.HALF_RING
        frames: list[list[list[int]]] = []
        num3 = 0
        for i in range(170):
            num4 = (num3 * 3) & 0xFF
            ring = [[0] * num for _ in range(3)]
            for j in range(num):
                colour_index = 0
                if 13 <= j < 26:
                    colour_index = 1
                elif 26 <= j < 39:
                    colour_index = 2
                elif 39 <= j < 54:
                    colour_index = 3
                base = self._colours[tb][colour_index]
                ring[0][j] = ((base[0] * num4) >> 8) * bright >> 8
                ring[1][j] = ((base[1] * num4) >> 8) * bright >> 8
                ring[2][j] = ((base[2] * num4) >> 8) * bright >> 8
            frames.append(self._project_half(tb, fans, ring))
            if i >= 85:
                num3 -= 1
            else:
                num3 += 1
        return frames

    def _runway(self, tb: int, fans: int, bright: int) -> list[list[list[int]]]:
        num = fans * self.HALF_RING
        frames = []
        for phase in range(2):
            for j in range(num + fans * 2 - 1):
                ring = [[0] * num for _ in range(3)]
                for idx in range(num):
                    colour_idx = 0 if idx <= j < idx + fans * 2 else 1
                    colour = self._colours[tb][colour_idx]
                    target = num - idx - 1 if phase else idx
                    ring[0][target] = (colour[0] * bright) >> 8
                    ring[1][target] = (colour[1] * bright) >> 8
                    ring[2][target] = (colour[2] * bright) >> 8
                frames.append(self._project_half(tb, fans, ring))
        return frames

    def _meteor(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> list[list[list[int]]]:
        num = fans * self.HALF_RING
        frames: list[list[list[int]]] = []
        weights = METEOR_WEIGHTS[fans - 1]
        for block in range(4):
            for j in range(num + fans * 2 - 1):
                ring = [[0] * num for _ in range(3)]
                weight_index = 0
                for idx in range(num):
                    r = g = b = 0
                    if idx <= j < idx + fans * 2 and weight_index < len(weights):
                        level = weights[weight_index]
                        colour = self._colours[tb][block]
                        r = ((colour[0] * level) >> 8) * bright >> 8
                        g = ((colour[1] * level) >> 8) * bright >> 8
                        b = ((colour[2] * level) >> 8) * bright >> 8
                        weight_index += 1
                    target = num - idx - 1 if direction != 0 else idx
                    ring[0][target] = r
                    ring[1][target] = g
                    ring[2][target] = b
                frames.append(self._project_half(tb, fans, ring))
        return frames

    def _color_cycle(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> list[list[list[int]]]:
        num = fans * self.HALF_RING
        template = [[0] * num for _ in range(3)]
        num2 = 0
        num3 = 0
        solid = COLOR_CYCLE_SOLID_LENGTHS[fans - 1]
        gaps = COLOR_CYCLE_GAP_LENGTHS[fans - 1]
        for block in range(3):
            num2 = num3
            num3 += solid
            for j in range(num2, min(num3, num)):
                colour = self._colours[tb][block]
                template[0][j] = colour[0]
                template[1][j] = colour[1]
                template[2][j] = colour[2]
            num2 = num3
            num3 += gaps
            for j in range(num2, min(num3, num)):
                template[0][j] = 0
                template[1][j] = 0
                template[2][j] = 0
            if tb == 0 and fans in (1, 4):
                num2 -= 1
                num3 -= 1
            if tb == 0 and fans == 2:
                num2 = num3
                num3 += 1
                if num2 < num:
                    template[0][num2] = 0
                    template[1][num2] = 0
                    template[2][num2] = 0
        frames: list[list[list[int]]] = []
        for k in range(num):
            ring = [[0] * num for _ in range(3)]
            idx = k
            for j in range(num):
                pos = num - j - 1 if direction == 0 else j
                ring[0][pos] = (template[0][idx] * bright) >> 8
                ring[1][pos] = (template[1][idx] * bright) >> 8
                ring[2][pos] = (template[2][idx] * bright) >> 8
                idx += 1
                if idx >= num:
                    idx = 0
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _stack(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> list[list[list[int]]]:
        """As the vendor app: one LED buffer is kept across all steps (lit LEDs stack up),
        and the frame list restarts for each colour block, so the last block's frames remain.
        """
        num = fans * self.HALF_RING
        span = fans
        ring = [[0] * num for _ in range(3)]
        frames: list[list[list[int]]] = []

        def paint(k: int, colour: list[int]) -> None:
            target = num - k - 1 if direction != 0 else k
            ring[0][target] = (colour[0] * bright) >> 8
            ring[1][target] = (colour[1] * bright) >> 8
            ring[2][target] = (colour[2] * bright) >> 8

        off = [0, 0, 0]
        for block in range(4):
            frames = []
            colour = self._colours[tb][block]
            num5 = 0
            for _ in range(self.HALF_RING):
                for j in range(num - num5):
                    for k in range(num - num5):
                        paint(k, colour if k <= j < k + span else off)
                    frames.append(self._project_half(tb, fans, ring))
                num5 += span
            for j in range(num):
                for k in range(num):
                    paint(k, colour if k > j else off)
                frames.append(self._project_half(tb, fans, ring))
        return frames

    def _twinkle(self, tb: int, fans: int, bright: int) -> list[list[list[int]]]:
        data = _load_twinkle_tables()
        colour_map = data["map"]
        value_frames = data["frames"]
        total_leds = fans * self.LEDS_PER_FAN
        frames = []
        palette = self._colours[tb]
        for frame_idx in range(len(value_frames)):
            frame = [[0] * total_leds for _ in range(3)]
            for led in range(total_leds):
                colour_idx = colour_map[led]
                intensity = value_frames[frame_idx][led]
                colour = palette[colour_idx]
                frame[0][led] = ((colour[0] * intensity) >> 8) * bright >> 8
                frame[1][led] = ((colour[1] * intensity) >> 8) * bright >> 8
                frame[2][led] = ((colour[2] * intensity) >> 8) * bright >> 8
            frames.append(frame)
        return frames

    def _project_half(
        self, tb: int, fans: int, ring: list[list[int]]
    ) -> list[list[int]]:
        frame = self._blank_frame(fans)
        for fan in range(fans):
            start = fan * self.HALF_RING
            self._fill_half(frame, tb, fan, ring, start)
        return frame

    def _fill_half(
        self,
        frame: list[list[int]],
        tb: int,
        fan: int,
        ring: list[list[int]],
        start: int,
    ) -> None:
        base = fan * self.LEDS_PER_FAN
        for offset in range(self.HALF_RING):
            ring_idx = start + offset
            if ring_idx >= len(ring[0]):
                break
            if tb == 0:
                dest = base + offset
            else:
                dest = base + self.HALF_RING + offset
            frame[0][dest] = ring[0][ring_idx]
            frame[1][dest] = ring[1][ring_idx]
            frame[2][dest] = ring[2][ring_idx]

    @staticmethod
    def _blank_frame(fans: int) -> list[list[int]]:
        return [[0] * (fans * TLEffectGenerator.LEDS_PER_FAN) for _ in range(3)]

    @staticmethod
    def _normalize_fans(fans: int) -> int:
        if fans <= 0 or fans > 4:
            return 4
        return fans
