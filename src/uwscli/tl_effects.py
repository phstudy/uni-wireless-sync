from __future__ import annotations

import importlib.resources as pkg_resources
import json
import math
import zlib
from enum import Enum, unique
from typing import Any, List


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


SLV3_USER_COLOUR: List[List[List[int]]] = [
    [[255, 0, 0], [0, 0, 255], [0, 255, 0], [255, 255, 0]],
    [[255, 0, 0], [0, 255, 0], [0, 0, 255], [255, 255, 0]],
    [[255, 0, 0], [255, 255, 0], [255, 0, 255], [255, 255, 0]],
    [[255, 0, 255], [0, 0, 255], [0, 255, 0], [255, 255, 0]],
]

RAINBOW_TABLES: dict[int, List[List[int]]] = {
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

METEOR_WEIGHTS: List[List[int]] = [
    [32, 255, 0, 0, 0, 0, 0, 0],
    [16, 64, 128, 255, 0, 0, 0, 0],
    [8, 16, 32, 64, 128, 255, 0, 0],
    [6, 10, 16, 32, 64, 96, 168, 255],
]

COLOR_CYCLE_SOLID_LENGTHS: List[int] = [1, 2, 5, 8]
COLOR_CYCLE_GAP_LENGTHS: List[int] = [3, 6, 8, 9]

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


class TLEffectGenerator:
    LEDS_PER_FAN = 26
    HALF_RING = 13

    def __init__(self) -> None:
        self._twinkle_cache = None

    def generate(
        self,
        effect: TLEffects,
        tb: int,
        fan_count: int,
        brightness: int,
        direction: int,
    ) -> List[List[List[int]]]:
        tb = 0 if tb >= 2 else tb
        fan_count = self._normalize_fans(fan_count)
        brightness = max(0, min(255, int(brightness)))
        direction = 0 if direction > 1 else max(0, int(direction))

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
            TLEffects.STAGGERED: lambda: self._staggered(
                tb, fan_count, brightness, direction
            ),
            TLEffects.TIDE: lambda: self._tide(tb, fan_count, brightness, direction),
            TLEffects.MIXING: lambda: self._mixing(
                tb, fan_count, brightness, direction
            ),
            TLEffects.VOICE: lambda: self._voice(tb, fan_count, brightness, direction),
            TLEffects.DOOR: lambda: self._door(tb, fan_count, brightness, direction),
            TLEffects.RENDER: lambda: self._render(
                tb, fan_count, brightness, direction
            ),
            TLEffects.RIPPLE: lambda: self._ripple(
                tb, fan_count, brightness, direction
            ),
            TLEffects.REFLECT: lambda: self._reflect(
                tb, fan_count, brightness, direction
            ),
            TLEffects.TAIL_CHASING: lambda: self._tail_chasing(
                tb, fan_count, brightness, direction
            ),
            TLEffects.PAINT: lambda: self._paint(tb, fan_count, brightness, direction),
            TLEffects.PING_PONG: lambda: self._ping_pong(
                tb, fan_count, brightness, direction
            ),
            TLEffects.STACK: lambda: self._stack(tb, fan_count, brightness, direction),
            TLEffects.COVER_CYCLE: lambda: self._cover_cycle(
                tb, fan_count, brightness, direction
            ),
            TLEffects.WAVE: lambda: self._wave(tb, fan_count, brightness, direction),
            TLEffects.RACING: lambda: self._racing(
                tb, fan_count, brightness, direction
            ),
            TLEffects.LOTTERY: lambda: self._lottery(
                tb, fan_count, brightness, direction
            ),
            TLEffects.INTERTWINE: lambda: self._intertwine(
                tb, fan_count, brightness, direction
            ),
            TLEffects.METEOR_SHOWER: lambda: self._meteor_shower(
                tb, fan_count, brightness, direction
            ),
            TLEffects.COLLIDE: lambda: self._collide(
                tb, fan_count, brightness, direction
            ),
            TLEffects.ELECTRIC_CURRENT: lambda: self._electric_current(
                tb, fan_count, brightness, direction
            ),
            TLEffects.KALEIDOSCOPE: lambda: self._kaleidoscope(
                tb, fan_count, brightness, direction
            ),
            TLEffects.TWINKLE: lambda: self._twinkle(tb, fan_count, brightness),
        }

        try:
            return handlers[effect]()
        except KeyError as exc:
            raise NotImplementedError(
                f"{effect.name} generator is not defined in the original TLMode set."
            ) from exc

    def _rainbow(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
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

    def _rainbow_morph(self, tb: int, fans: int, bright: int) -> List[List[List[int]]]:
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
    ) -> List[List[List[int]]]:
        ring = [[0] * (fans * self.HALF_RING) for _ in range(3)]
        for block in range(4):
            colour = SLV3_USER_COLOUR[tb][block]
            for idx in range(block * self.HALF_RING, (block + 1) * self.HALF_RING):
                ring[0][idx] = (colour[0] * bright) >> 8
                ring[1][idx] = (colour[1] * bright) >> 8
                ring[2][idx] = (colour[2] * bright) >> 8
        frame = self._project_half(tb, fans, ring)
        return [frame for _ in range(30)]

    def _breathing(self, tb: int, fans: int, bright: int) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        frames: List[List[List[int]]] = []
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
                base = SLV3_USER_COLOUR[tb][colour_index]
                ring[0][j] = (base[0] * num4 * bright) >> 16
                ring[1][j] = (base[1] * num4 * bright) >> 16
                ring[2][j] = (base[2] * num4 * bright) >> 16
            frames.append(self._project_half(tb, fans, ring))
            if i >= 85:
                num3 -= 1
            else:
                num3 += 1
        return frames

    def _runway(self, tb: int, fans: int, bright: int) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        frames = []
        for phase in range(2):
            for j in range(num + fans * 2 - 1):
                ring = [[0] * num for _ in range(3)]
                for idx in range(num):
                    colour_idx = 0 if idx <= j < idx + fans * 2 else 1
                    colour = SLV3_USER_COLOUR[tb][colour_idx]
                    target = num - idx - 1 if phase else idx
                    ring[0][target] = (colour[0] * bright) >> 8
                    ring[1][target] = (colour[1] * bright) >> 8
                    ring[2][target] = (colour[2] * bright) >> 8
                frames.append(self._project_half(tb, fans, ring))
        return frames

    def _meteor(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        frames: List[List[List[int]]] = []
        weights = METEOR_WEIGHTS[fans - 1]
        for block in range(4):
            for j in range(num + fans * 2 - 1):
                ring = [[0] * num for _ in range(3)]
                weight_index = 0
                for idx in range(num):
                    r = g = b = 0
                    if idx <= j < idx + fans * 2 and weight_index < len(weights):
                        level = weights[weight_index]
                        colour = SLV3_USER_COLOUR[tb][block]
                        r = (colour[0] * level * bright) >> 16
                        g = (colour[1] * level * bright) >> 16
                        b = (colour[2] * level * bright) >> 16
                        weight_index += 1
                    target = num - idx - 1 if direction != 0 else idx
                    ring[0][target] = r
                    ring[1][target] = g
                    ring[2][target] = b
                frames.append(self._project_half(tb, fans, ring))
        return frames

    def _color_cycle(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
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
                colour = SLV3_USER_COLOUR[tb][block]
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
        frames: List[List[List[int]]] = []
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

    def _staggered(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        palette = SLV3_USER_COLOUR[tb]
        segments = max(1, len(palette) * 2)
        segment_len = max(1, num // segments)
        pattern: List[int] = []
        for segment in range(segments):
            colour_idx = segment // 2
            value = colour_idx if segment % 2 == 0 else -1
            for _ in range(segment_len):
                if len(pattern) >= num:
                    break
                pattern.append(value)
        while len(pattern) < num:
            pattern.append(-1)

        frames: List[List[List[int]]] = []
        for shift in range(num):
            ring = [[0] * num for _ in range(3)]
            for pos in range(num):
                idx = pattern[(pos + shift) % num]
                if idx < 0:
                    continue
                dest = self._directed_index(pos, num, direction)
                colour = palette[idx % len(palette)]
                self._set_scaled_colour(ring, dest, colour, bright)
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _tide(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        if num == 0:
            return []
        palette = SLV3_USER_COLOUR[tb]
        frames: List[List[List[int]]] = []
        frame_count = num * 2
        for step in range(frame_count):
            ring = [[0] * num for _ in range(3)]
            phase = (2.0 * math.pi * step) / frame_count
            for pos in range(num):
                wave = math.sin(phase + (math.pi * pos) / max(1, num))
                intensity = int((wave + 1.0) * 127.5)
                dest = self._directed_index(pos, num, direction)
                band = (pos * len(palette)) // max(1, num)
                self._set_scaled_colour(
                    ring, dest, palette[band % len(palette)], bright, intensity
                )
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _mixing(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        if num == 0:
            return []
        base_a = SLV3_USER_COLOUR[tb][0]
        base_b = SLV3_USER_COLOUR[tb][2]
        frames: List[List[List[int]]] = []
        frame_count = num * 2
        for step in range(frame_count):
            ring = [[0] * num for _ in range(3)]
            for pos in range(num):
                phase = 2.0 * math.pi * (step + pos) / max(1, num)
                ratio = (math.sin(phase) + 1.0) * 0.5
                blended = [
                    int(
                        round(
                            base_a[channel]
                            + (base_b[channel] - base_a[channel]) * ratio
                        )
                    )
                    for channel in range(3)
                ]
                dest = self._directed_index(pos, num, direction)
                self._set_scaled_colour(ring, dest, blended, bright)
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _voice(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        palette = SLV3_USER_COLOUR[tb]
        frames: List[List[List[int]]] = []
        frame_count = max(1, self.HALF_RING * 4)
        for step in range(frame_count):
            ring = [[0] * num for _ in range(3)]
            for fan in range(fans):
                colour = palette[fan % len(palette)]
                amplitude = (
                    int(
                        (math.sin(step * 0.35 + fan) + 1.0) * (self.HALF_RING - 1) * 0.5
                    )
                    + 1
                )
                amplitude = max(1, min(self.HALF_RING, amplitude))
                for offset in range(amplitude):
                    pos = fan * self.HALF_RING + offset
                    dest = self._directed_index(pos, num, direction)
                    intensity = max(80, 255 - offset * 20)
                    self._set_scaled_colour(ring, dest, colour, bright, intensity)
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _door(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        half = self.HALF_RING
        if half == 0:
            return []
        center = half // 2
        palette = SLV3_USER_COLOUR[tb]
        frames: List[List[List[int]]] = []
        frame_count = half * 2
        for step in range(frame_count):
            ring = [[0] * num for _ in range(3)]
            extent = step if step < half else (frame_count - step - 1)
            extent = max(0, extent)
            for fan in range(fans):
                colour = palette[(fan + step) % len(palette)]
                base = fan * half
                for offset in range(extent + 1):
                    intensity = max(64, 255 - offset * 30)
                    left = center - offset
                    right = center + offset
                    if left >= 0:
                        dest = self._directed_index(base + left, num, direction)
                        self._set_scaled_colour(ring, dest, colour, bright, intensity)
                    if right < half and right != left:
                        dest = self._directed_index(base + right, num, direction)
                        self._set_scaled_colour(ring, dest, colour, bright, intensity)
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _render(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        palette = SLV3_USER_COLOUR[tb]
        frames: List[List[List[int]]] = []
        period = max(1, num * 2)
        for step in range(period):
            ring = [[0] * num for _ in range(3)]
            fill = step if step < num else period - step
            fill = max(0, min(num, fill))
            colour = palette[step % len(palette)]
            for pos in range(fill):
                dest = self._directed_index(pos, num, direction)
                self._set_scaled_colour(ring, dest, colour, bright)
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _ripple(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        if num == 0:
            return []
        palette = SLV3_USER_COLOUR[tb]
        frames: List[List[List[int]]] = []
        for step in range(num):
            ring = [[0] * num for _ in range(3)]
            for pos in range(num):
                distance = min((pos - step) % num, (step - pos) % num)
                intensity = max(0, 255 - int(distance * (255 / max(1, self.HALF_RING))))
                if intensity <= 0:
                    continue
                dest = self._directed_index(pos, num, direction)
                colour = palette[
                    (pos // max(1, self.HALF_RING // len(palette) or 1)) % len(palette)
                ]
                self._set_scaled_colour(ring, dest, colour, bright, intensity)
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _reflect(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        palette = SLV3_USER_COLOUR[tb]
        frames: List[List[List[int]]] = []
        period = max(1, num * 2)
        for step in range(period):
            ring = [[0] * num for _ in range(3)]
            idx = step if step < num else period - step - 1
            idx = max(0, min(num - 1, idx))
            left = idx
            right = num - idx - 1
            colour_left = palette[step % len(palette)]
            colour_right = palette[(step + 1) % len(palette)]
            dest_left = self._directed_index(left, num, direction)
            dest_right = self._directed_index(right, num, direction)
            self._set_scaled_colour(ring, dest_left, colour_left, bright)
            if dest_right != dest_left:
                self._set_scaled_colour(ring, dest_right, colour_right, bright)
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _tail_chasing(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        if num == 0:
            return []
        palette = SLV3_USER_COLOUR[tb]
        frames: List[List[List[int]]] = []
        tail = max(4, self.HALF_RING // 2)
        for step in range(num):
            ring = [[0] * num for _ in range(3)]
            lead = step % num
            colour = palette[(step // max(1, tail)) % len(palette)]
            for offset in range(tail):
                pos = (lead - offset) % num
                intensity = max(0, 255 - offset * (255 // max(1, tail)))
                if intensity <= 0:
                    continue
                dest = self._directed_index(pos, num, direction)
                self._set_scaled_colour(ring, dest, colour, bright, intensity)
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _paint(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        palette = SLV3_USER_COLOUR[tb]
        frames: List[List[List[int]]] = []
        block_len = self.HALF_RING
        total_steps = max(1, block_len * len(palette))
        for step in range(total_steps):
            ring = [[0] * num for _ in range(3)]
            colour_index = step // max(1, block_len)
            fill = step % max(1, block_len)
            for fan in range(fans):
                colour = palette[(colour_index + fan) % len(palette)]
                base = fan * self.HALF_RING
                for pos in range(min(fill + 1, self.HALF_RING)):
                    dest = self._directed_index(base + pos, num, direction)
                    self._set_scaled_colour(ring, dest, colour, bright)
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _ping_pong(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        track = self.HALF_RING
        if track <= 1:
            return []
        num = fans * track
        palette = SLV3_USER_COLOUR[tb]
        period = max(1, 2 * (track - 1))
        frames: List[List[List[int]]] = []
        for step in range(period):
            ring = [[0] * num for _ in range(3)]
            offset = step if step < track else period - step
            for fan in range(fans):
                colour = palette[fan % len(palette)]
                base = fan * track
                pos = base + offset
                dest = self._directed_index(pos, num, direction)
                self._set_scaled_colour(ring, dest, colour, bright)
                if offset > 0:
                    prev_pos = base + offset - 1
                    dest_prev = self._directed_index(prev_pos, num, direction)
                    self._set_scaled_colour(ring, dest_prev, colour, bright, 128)
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _stack(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        span = fans
        frames: List[List[List[int]]] = []
        for block in range(4):
            num5 = 0
            num6 = 0
            while num6 < self.HALF_RING:
                for j in range(num - num5):
                    ring = [[0] * num for _ in range(3)]
                    for k in range(num - num5):
                        colour = (
                            SLV3_USER_COLOUR[tb][block]
                            if k <= j < k + span
                            else [0, 0, 0]
                        )
                        target = num - k - 1 if direction != 0 else k
                        ring[0][target] = (colour[0] * bright) >> 8
                        ring[1][target] = (colour[1] * bright) >> 8
                        ring[2][target] = (colour[2] * bright) >> 8
                    frames.append(self._project_half(tb, fans, ring))
                num6 += 1
                num5 += span
            for j in range(num):
                ring = [[0] * num for _ in range(3)]
                for k in range(num):
                    colour = SLV3_USER_COLOUR[tb][block] if k > j else [0, 0, 0]
                    target = num - k - 1 if direction != 0 else k
                    ring[0][target] = (colour[0] * bright) >> 8
                    ring[1][target] = (colour[1] * bright) >> 8
                    ring[2][target] = (colour[2] * bright) >> 8
                frames.append(self._project_half(tb, fans, ring))
        return frames

    def _cover_cycle(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        if num == 0:
            return []
        palette = SLV3_USER_COLOUR[tb]
        block = max(1, self.HALF_RING // 2)
        frames: List[List[List[int]]] = []
        for step in range(num):
            ring = [[0] * num for _ in range(3)]
            for offset in range(block):
                pos = (step + offset) % num
                dest = self._directed_index(pos, num, direction)
                colour = palette[
                    (offset // max(1, block // len(palette))) % len(palette)
                ]
                intensity = max(80, 255 - offset * (200 // max(1, block)))
                self._set_scaled_colour(ring, dest, colour, bright, intensity)
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _wave(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        if num == 0:
            return []
        palette = SLV3_USER_COLOUR[tb]
        frames: List[List[List[int]]] = []
        frame_count = num * 2
        for step in range(frame_count):
            ring = [[0] * num for _ in range(3)]
            phase = (2.0 * math.pi * step) / frame_count
            for pos in range(num):
                wave = math.sin(phase + (2.0 * math.pi * pos) / max(1, num))
                intensity = int((wave + 1.0) * 127.5)
                colour = palette[(pos + step) % len(palette)]
                dest = self._directed_index(pos, num, direction)
                self._set_scaled_colour(ring, dest, colour, bright, intensity)
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _racing(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        if num == 0:
            return []
        palette = SLV3_USER_COLOUR[tb]
        racers = max(1, min(4, fans + 1))
        frames: List[List[List[int]]] = []
        for step in range(num):
            ring = [[0] * num for _ in range(3)]
            for racer in range(racers):
                speed = racer + 1
                position = (step * (speed + 1) + racer * (num // racers)) % num
                dest = self._directed_index(position, num, direction)
                intensity = max(120, 255 - racer * 45)
                self._set_scaled_colour(
                    ring, dest, palette[racer % len(palette)], bright, intensity
                )
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _lottery(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        palette = SLV3_USER_COLOUR[tb]
        frames: List[List[List[int]]] = []
        state = 0x135724
        picks_per_frame = max(1, min(num, fans * 3))
        frame_count = max(1, num // 2)
        for _ in range(frame_count):
            ring = [[0] * num for _ in range(3)]
            local_state = state
            for pick in range(picks_per_frame):
                local_state = (local_state * 1103515245 + 12345) & 0x7FFFFFFF
                pos = local_state % max(1, num)
                dest = self._directed_index(pos, num, direction)
                intensity = max(100, 255 - pick * 25)
                colour = palette[(pick + local_state) % len(palette)]
                self._set_scaled_colour(ring, dest, colour, bright, intensity)
            frames.append(self._project_half(tb, fans, ring))
            state = (state * 1664525 + 1013904223) & 0xFFFFFFFF
        return frames

    def _intertwine(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        if num == 0:
            return []
        palette = SLV3_USER_COLOUR[tb]
        frames: List[List[List[int]]] = []
        strand_len = max(1, num // 2)
        for step in range(num):
            ring = [[0] * num for _ in range(3)]
            for strand in range(strand_len):
                forward_pos = (2 * strand + step) % num
                backward_pos = (2 * strand + 1 - step) % num
                colour_a = palette[strand % len(palette)]
                colour_b = palette[(strand + 1) % len(palette)]
                dest_a = self._directed_index(forward_pos, num, direction)
                dest_b = self._directed_index(backward_pos, num, direction)
                self._set_scaled_colour(ring, dest_a, colour_a, bright)
                self._set_scaled_colour(ring, dest_b, colour_b, bright, 192)
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _meteor_shower(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        if num == 0:
            return []
        palette = SLV3_USER_COLOUR[tb]
        meteors = max(1, min(4, fans * 2))
        spacing = max(1, num // meteors)
        tail = max(3, self.HALF_RING // 2)
        frames: List[List[List[int]]] = []
        for step in range(num):
            ring = [[0] * num for _ in range(3)]
            for meteor in range(meteors):
                start = (step + meteor * spacing) % num
                colour = palette[meteor % len(palette)]
                for offset in range(tail):
                    pos = (start - offset) % num
                    intensity = max(0, 255 - offset * (200 // max(1, tail)))
                    if intensity <= 0:
                        continue
                    dest = self._directed_index(pos, num, direction)
                    self._set_scaled_colour(ring, dest, colour, bright, intensity)
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _collide(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        half = self.HALF_RING
        if half == 0:
            return []
        num = fans * half
        palette = SLV3_USER_COLOUR[tb]
        frames: List[List[List[int]]] = []
        period = half
        for step in range(period * 2):
            ring = [[0] * num for _ in range(3)]
            offset = step if step < period else period * 2 - step - 1
            offset = max(0, min(half - 1, offset))
            for fan in range(fans):
                base = fan * half
                left = base + offset
                right = base + half - offset - 1
                colour_left = palette[fan % len(palette)]
                colour_right = palette[(fan + 1) % len(palette)]
                dest_left = self._directed_index(left, num, direction)
                dest_right = self._directed_index(right, num, direction)
                self._set_scaled_colour(ring, dest_left, colour_left, bright)
                if dest_right != dest_left:
                    self._set_scaled_colour(ring, dest_right, colour_right, bright)
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _electric_current(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        if num == 0:
            return []
        palette = SLV3_USER_COLOUR[tb]
        frames: List[List[List[int]]] = []
        frame_count = max(1, num)
        for step in range(frame_count):
            ring = [[0] * num for _ in range(3)]
            for pos in range(num):
                noise = math.sin(step * 1.7 + pos * 2.3) + math.sin(pos * 5.1)
                intensity = int(abs(noise) * 127.0)
                if intensity <= 32:
                    continue
                dest = self._directed_index(pos, num, direction)
                colour = palette[(pos + step) % len(palette)]
                self._set_scaled_colour(
                    ring, dest, colour, bright, min(255, 96 + intensity)
                )
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _kaleidoscope(
        self, tb: int, fans: int, bright: int, direction: int
    ) -> List[List[List[int]]]:
        num = fans * self.HALF_RING
        if num == 0:
            return []
        palette = SLV3_USER_COLOUR[tb]
        segments = max(1, len(palette) * 4)
        segment_len = max(1, num // segments)
        base_pattern: List[List[int]] = []
        for segment in range(segments):
            colour = palette[segment % len(palette)]
            for _ in range(segment_len):
                if len(base_pattern) >= num:
                    break
                base_pattern.append(colour)
        while len(base_pattern) < num:
            base_pattern.append(palette[len(base_pattern) % len(palette)])

        frames: List[List[List[int]]] = []
        for step in range(num):
            ring = [[0] * num for _ in range(3)]
            for pos in range(num):
                mirrored = min(pos, num - pos - 1)
                colour = base_pattern[(mirrored + step) % len(base_pattern)]
                dest = self._directed_index(pos, num, direction)
                self._set_scaled_colour(ring, dest, colour, bright)
            frames.append(self._project_half(tb, fans, ring))
        return frames

    def _twinkle(self, tb: int, fans: int, bright: int) -> List[List[List[int]]]:
        data = _load_twinkle_tables()
        colour_map = data["map"]
        value_frames = data["frames"]
        total_leds = fans * self.LEDS_PER_FAN
        frames = []
        palette = SLV3_USER_COLOUR[tb]
        for frame_idx in range(len(value_frames)):
            frame = [[0] * total_leds for _ in range(3)]
            for led in range(total_leds):
                colour_idx = colour_map[led]
                intensity = value_frames[frame_idx][led]
                colour = palette[colour_idx]
                frame[0][led] = (colour[0] * intensity * bright) >> 16
                frame[1][led] = (colour[1] * intensity * bright) >> 16
                frame[2][led] = (colour[2] * intensity * bright) >> 16
            frames.append(frame)
        return frames

    @staticmethod
    def _set_scaled_colour(
        ring: List[List[int]],
        index: int,
        colour: List[int],
        bright: int,
        intensity: int = 255,
    ) -> None:
        intensity = max(0, min(255, int(intensity)))
        bright = max(0, min(255, int(bright)))
        factor = bright * intensity
        ring[0][index] = (colour[0] * factor + 0x7FFF) >> 16
        ring[1][index] = (colour[1] * factor + 0x7FFF) >> 16
        ring[2][index] = (colour[2] * factor + 0x7FFF) >> 16

    @staticmethod
    def _directed_index(pos: int, total: int, direction: int) -> int:
        if direction == 0:
            return total - pos - 1
        return pos

    def _project_half(
        self, tb: int, fans: int, ring: List[List[int]]
    ) -> List[List[int]]:
        frame = self._blank_frame(fans)
        for fan in range(fans):
            start = fan * self.HALF_RING
            self._fill_half(frame, tb, fan, ring, start)
        return frame

    def _fill_half(
        self,
        frame: List[List[int]],
        tb: int,
        fan: int,
        ring: List[List[int]],
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
    def _blank_frame(fans: int) -> List[List[int]]:
        return [[0] * (fans * TLEffectGenerator.LEDS_PER_FAN) for _ in range(3)]

    @staticmethod
    def _normalize_fans(fans: int) -> int:
        if fans <= 0 or fans > 4:
            return 4
        return fans
