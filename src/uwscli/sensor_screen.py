"""Draw a sensor value as a ring gauge for the 400x400 TL Wireless LCD."""

from __future__ import annotations

from typing import Any

from .sensors import Metric

SIZE = 400
# The vendor app's sensor colours.
COLOURS: dict[str, tuple[int, int, int]] = {
    "blue": (0, 160, 255),
    "green": (0, 220, 110),
    "purple": (170, 70, 255),
    "red": (255, 50, 60),
}
_START = 135  # degrees; the gauge runs clockwise over 270 degrees, open at the bottom
_SWEEP = 270


def _font(size: int) -> Any:
    from PIL import ImageFont

    try:
        return ImageFont.load_default(size=size)
    except TypeError:  # pragma: no cover - Pillow without FreeType
        return ImageFont.load_default()


def render(value: float, metric: Metric, colour: str = "blue") -> Any:
    """Return a Pillow image of the gauge."""
    from PIL import Image, ImageDraw

    accent = COLOURS[colour]
    image = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    box = (40, 40, SIZE - 40, SIZE - 40)
    width = 26
    draw.arc(box, _START, _START + _SWEEP, fill=(40, 40, 46), width=width)
    fraction = max(0.0, min(1.0, value / metric.maximum)) if metric.maximum else 0.0
    if fraction > 0:
        draw.arc(box, _START, _START + _SWEEP * fraction, fill=accent, width=width)
    centre = SIZE // 2
    draw.text(
        (centre, centre - 10),
        f"{value:.0f}",
        font=_font(110),
        fill=(255, 255, 255),
        anchor="mm",
    )
    draw.text(
        (centre, centre + 62), metric.unit, font=_font(34), fill=accent, anchor="mm"
    )
    draw.text(
        (centre, SIZE - 62),
        metric.label,
        font=_font(40),
        fill=(200, 200, 205),
        anchor="mm",
    )
    return image


def render_clock(now: Any, colour: str = "blue") -> Any:
    """Return a Pillow image with the time (HH:MM), seconds as a ring, and the date."""
    from PIL import Image, ImageDraw

    accent = COLOURS[colour]
    image = Image.new("RGB", (SIZE, SIZE), (0, 0, 0))
    draw = ImageDraw.Draw(image)
    box = (40, 40, SIZE - 40, SIZE - 40)
    draw.arc(box, 0, 360, fill=(40, 40, 46), width=10)
    if now.second:
        draw.arc(box, -90, -90 + 6 * now.second, fill=accent, width=10)
    centre = SIZE // 2
    draw.text(
        (centre, centre - 10),
        now.strftime("%H:%M"),
        font=_font(100),
        fill=(255, 255, 255),
        anchor="mm",
    )
    draw.text(
        (centre, centre + 70),
        now.strftime("%a %d %b"),
        font=_font(32),
        fill=accent,
        anchor="mm",
    )
    return image
