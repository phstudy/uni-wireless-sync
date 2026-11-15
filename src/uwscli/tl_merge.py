"""Merged TL lighting: one effect running across several fan groups, as the vendor app's
"merge" mode does.

The app renders one strip with a dot per LED column (13 per fan, the front and behind
LEDs of a column show the same colour), in the order the groups are arranged, then
gives each group its slice. Rainbow morph and twinkle are not merged; the app runs them
on every group on its own.
"""

from __future__ import annotations

from .tl_effects import TLEffects, clamp_colour

Strip = list[list[list[int]]]  # frames x 3 channels x dots

DOTS_PER_FAN = 13
# The app's merge effects and their strip generator numbers.
MERGE_EFFECTS: dict[TLEffects, int] = {
    TLEffects.RAINBOW: 1,
    TLEffects.STATIC_COLOR: 3,
    TLEffects.BREATHING: 4,
    TLEffects.RUNWAY: 5,
    TLEffects.METEOR: 6,
    TLEffects.COLOR_CYCLE: 9,
    TLEffects.COVER_CYCLE: 10,
    TLEffects.WAVE: 11,
    TLEffects.METEOR_SHOWER: 12,
}
# Merge choices the app runs on each group separately.
PER_GROUP_EFFECTS = (TLEffects.RAINBOW_MORPH, TLEffects.TWINKLE)
MERGE_SPEED_BASE = 12  # ms per speed step (the app's per-group effects use 11)

_RAINBOW = [
    [
        255,
        224,
        192,
        160,
        128,
        96,
        64,
        32,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        0,
        32,
        64,
        96,
        128,
        160,
        192,
        224,
    ],
    [
        0,
        32,
        64,
        96,
        128,
        160,
        192,
        224,
        255,
        224,
        192,
        160,
        128,
        96,
        64,
        32,
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
        32,
        64,
        96,
        128,
        160,
        192,
        224,
        255,
        224,
        192,
        160,
        128,
        96,
        64,
        32,
    ],
]
_METEOR_TAIL = [12, 16, 20, 24, 32, 40, 48, 64, 96, 128, 192, 255]
_COLOR_CYCLE = [1] * 6 + [0] * 10 + [2] * 6 + [0] * 10 + [3] * 6 + [0] * 10
_WAVE = [
    0,
    0,
    4,
    8,
    16,
    32,
    64,
    96,
    128,
    160,
    192,
    255,
    255,
    192,
    160,
    128,
    96,
    64,
    32,
    16,
    8,
    4,
    0,
    0,
]
_SHOWER_LEVEL = [
    255,
    128,
    64,
    32,
    16,
    8,
    0,
    0,
    0,
    0,
    255,
    64,
    32,
    16,
    0,
    0,
    0,
    0,
    0,
    255,
    192,
    168,
    128,
    96,
]
_SHOWER_LEVEL += [
    64,
    32,
    16,
    8,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
    255,
    128,
    64,
    32,
    16,
    8,
    0,
    0,
    0,
    0,
    0,
    0,
    0,
]
_SHOWER_COLOUR = [0] * 10 + [1] * 9 + [2] * 16 + [3] * 13


def _clamp_dots(dots: int) -> int:
    return dots if 24 <= dots <= 720 else 24


def _repeat(
    pattern: list[list[int]], dots: int, bright: int | None = None
) -> list[list[int]]:
    """Tile a pattern over the strip (optionally scaling by brightness)."""
    width = len(pattern[0])
    out = [[0] * dots for _ in range(3)]
    for dot in range(dots):
        for c in range(3):
            value = pattern[c][dot % width]
            out[c][dot] = value if bright is None else value * bright >> 8
    return out


def _rainbow(dots: int, bright: int, direction: int) -> Strip:
    frames = []
    for i in range(24):
        pattern = [[0] * 24 for _ in range(3)]
        for j in range(24):
            target = j if direction else 23 - j
            for c in range(3):
                pattern[c][target] = _RAINBOW[c][(i + j) % 24] * bright >> 8
        frames.append(_repeat(pattern, dots))
    return frames


def _static(dots: int, bright: int, colours: list[list[int]]) -> Strip:
    return [[[colours[0][c] * bright >> 8] * dots for c in range(3)]]


def _breathing(dots: int, bright: int, colours: list[list[int]]) -> Strip:
    frames = []
    step = 0
    for i in range(170):
        level = (step * 3) & 0xFF
        frames.append(
            [[(colours[0][c] * level >> 8) * bright >> 8] * dots for c in range(3)]
        )
        step = step - 1 if i >= 85 else step + 1
    return frames


def _runway(dots: int, bright: int, colours: list[list[int]]) -> Strip:
    frames = []
    for i in range(2):
        for j in range(dots + 11):
            frame = [[0] * dots for _ in range(3)]
            for k in range(dots):
                colour = colours[0] if k <= j < k + 12 else colours[1]
                pos = k if i == 0 else dots - k - 1
                for c in range(3):
                    frame[c][pos] = colour[c] * bright >> 8
            frames.append(frame)
    return frames


def _meteor(dots: int, bright: int, direction: int, colours: list[list[int]]) -> Strip:
    length = dots + 12
    trail = [[0] * length for _ in range(3)]
    for i, weight in enumerate(_METEOR_TAIL):
        for c in range(3):
            trail[c][i] = colours[0][c] * weight >> 8
    frames = []
    offset = 12
    for _ in range(length):
        frame = [[0] * dots for _ in range(3)]
        for i in range(dots):
            pos = dots - i - 1 if direction == 1 else i
            src = offset + i
            if src >= length:
                src -= length
            for c in range(3):
                frame[c][pos] = trail[c][src] * bright >> 8
        frames.append(frame)
        offset = offset - 1 if offset else length - 1
    return frames


def _rotating(
    dots: int, direction: int, cells: list[list[int]], bright_after: int | None
) -> Strip:
    """Frames that rotate a pattern of `cells` (3 x width) one step per frame."""
    width = len(cells[0])
    frames = []
    for i in range(width):
        pattern = [[0] * width for _ in range(3)]
        for n in range(width):
            target = n if direction else width - n - 1
            for c in range(3):
                pattern[c][target] = cells[c][(i + n) % width]
        frames.append(_repeat(pattern, dots, bright_after))
    return frames


def _color_cycle(
    dots: int, bright: int, direction: int, colours: list[list[int]]
) -> Strip:
    cells = [
        [
            0 if index == 0 else colours[index - 1][c] * bright >> 8
            for index in _COLOR_CYCLE
        ]
        for c in range(3)
    ]
    return _rotating(dots, direction, cells, None)


def _cover_cycle(
    dots: int, bright: int, direction: int, colours: list[list[int]]
) -> Strip:
    frames = []
    for i in range(2):
        for j in range(dots):
            line = [[0] * dots for _ in range(3)]
            for k in range(dots):
                colour = colours[i] if k < j else colours[1 if i == 0 else 0]
                for c in range(3):
                    line[c][k] = colour[c] * bright >> 8
            frames.append(
                [
                    [
                        line[c][k if direction == 0 else dots - k - 1]
                        for k in range(dots)
                    ]
                    for c in range(3)
                ]
            )
    return frames


def _wave(dots: int, bright: int, direction: int, colours: list[list[int]]) -> Strip:
    cells = [[colours[0][c] * w >> 8 for w in _WAVE] for c in range(3)]
    return _rotating(dots, direction, cells, bright)


def _meteor_shower(
    dots: int, bright: int, direction: int, colours: list[list[int]]
) -> Strip:
    cells = [
        [
            colours[index][c] * level >> 8
            for index, level in zip(_SHOWER_COLOUR, _SHOWER_LEVEL)
        ]
        for c in range(3)
    ]
    return _rotating(dots, direction, cells, bright)


def render_strip(
    effect: TLEffects, dots: int, bright: int, direction: int, colours: list[list[int]]
) -> Strip:
    """The app's strip for a merge effect over `dots` columns (at least 24 are rendered)."""
    table = [clamp_colour(list(c)) for c in colours[:6]]
    table += [[0, 0, 0]] * (6 - len(table))
    dots = _clamp_dots(dots)
    bright = max(0, min(255, bright))
    direction = 1 if direction == 1 else 0
    mode = MERGE_EFFECTS[effect]
    if mode == 1:
        return _rainbow(dots, bright, direction)
    if mode == 3:
        return _static(dots, bright, table)
    if mode == 4:
        return _breathing(dots, bright, table)
    if mode == 5:
        return _runway(dots, bright, table)
    if mode == 6:
        return _meteor(dots, bright, direction, table)
    if mode == 9:
        return _color_cycle(dots, bright, direction, table)
    if mode == 10:
        return _cover_cycle(dots, bright, direction, table)
    if mode == 11:
        return _wave(dots, bright, direction, table)
    return _meteor_shower(dots, bright, direction, table)


def group_slice(strip: Strip, start: int, stop: int, direction: int) -> Strip:
    """A group's frames from its dots [start, stop]: each dot lights the front and the
    behind LED of its column; direction 1 reverses the group."""
    groups = (stop + 1 - start) // DOTS_PER_FAN
    frames = []
    for frame in strip:
        out = [[0] * (groups * 2 * DOTS_PER_FAN) for _ in range(3)]
        for fan in range(groups):
            for j in range(DOTS_PER_FAN):
                src = start + fan * DOTS_PER_FAN + j
                if direction == 1:
                    src = stop + start - src
                for half in (0, DOTS_PER_FAN):
                    for c in range(3):
                        out[c][fan * 2 * DOTS_PER_FAN + half + j] = frame[c][src]
        frames.append(out)
    return frames


def merge_frames(
    effect: TLEffects,
    fans: list[int],
    *,
    bright: int,
    direction: int,
    colours: list[list[int]],
    reversed_groups: list[bool] | None = None,
) -> list[Strip]:
    """Frames for each group (in order; `fans` is each group's fan count)."""
    reversed_groups = reversed_groups or [False] * len(fans)
    strip = render_strip(effect, sum(fans) * DOTS_PER_FAN, bright, direction, colours)
    out = []
    start = 0
    for count, reverse in zip(fans, reversed_groups):
        stop = start + count * DOTS_PER_FAN - 1
        out.append(group_slice(strip, start, stop, 1 if reverse else 0))
        start = stop + 1
    return out


def merge_interval(speed: int) -> int:
    """Frame interval in ms: the app's speed level (1-5 -> 7..3) times 12 ms."""
    if not 1 <= speed <= 5:
        raise ValueError("speed must be 1-5")
    return (8 - speed) * MERGE_SPEED_BASE
