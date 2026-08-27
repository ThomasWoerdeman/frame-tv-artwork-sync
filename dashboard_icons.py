#!/usr/bin/env python3
"""
Weather icons for the dashboard card.

Uses Meteocons (https://github.com/basmilius/meteocons, MIT) — real designed
icons, vendored as 512px PNGs under assets/weather-icons and mapped from WMO
weather codes with day and night variants.

If an icon file is missing (a trimmed image, a broken mount), the drawn
fallbacks below keep the card working rather than leaving a hole in it.
"""

import logging
import math
import os
from functools import lru_cache
from pathlib import Path
from typing import Optional, Tuple

from PIL import Image

logger = logging.getLogger(__name__)

ICON_DIR = Path(os.getenv('WEATHER_ICON_DIR',
                          str(Path(__file__).parent / 'assets' / 'weather-icons')))

# Colours for the drawn fallbacks only.
ACCENT = (240, 200, 132)
RAIN = (130, 186, 236)
SNOW = (230, 240, 250)
MUTED = (206, 212, 224)
CLOUD = (238, 242, 248)

# WMO weather code -> (day icon, night icon).
# https://open-meteo.com/en/docs — "Weather variable documentation".
WMO_ICONS = {
    0: ('clear-day', 'clear-night'),
    1: ('clear-day', 'clear-night'),
    2: ('partly-cloudy-day', 'partly-cloudy-night'),
    3: ('overcast-day', 'overcast-night'),
    45: ('fog-day', 'fog-night'),
    48: ('fog-day', 'fog-night'),
    51: ('partly-cloudy-day-drizzle', 'partly-cloudy-night-drizzle'),
    53: ('overcast-day-drizzle', 'overcast-night-drizzle'),
    55: ('extreme-day-drizzle', 'extreme-night-drizzle'),
    56: ('overcast-day-sleet', 'overcast-night-sleet'),
    57: ('extreme-day-sleet', 'extreme-night-sleet'),
    61: ('partly-cloudy-day-rain', 'partly-cloudy-night-rain'),
    63: ('overcast-day-rain', 'overcast-night-rain'),
    65: ('extreme-day-rain', 'extreme-night-rain'),
    66: ('overcast-day-sleet', 'overcast-night-sleet'),
    67: ('extreme-day-sleet', 'extreme-night-sleet'),
    71: ('partly-cloudy-day-snow', 'partly-cloudy-night-snow'),
    73: ('overcast-day-snow', 'overcast-night-snow'),
    75: ('extreme-day-snow', 'extreme-night-snow'),
    77: ('overcast-day-snow', 'overcast-night-snow'),
    80: ('partly-cloudy-day-rain', 'partly-cloudy-night-rain'),
    81: ('overcast-day-rain', 'overcast-night-rain'),
    82: ('extreme-day-rain', 'extreme-night-rain'),
    85: ('overcast-day-snow', 'overcast-night-snow'),
    86: ('extreme-day-snow', 'extreme-night-snow'),
    95: ('thunderstorms-day', 'thunderstorms-night'),
    96: ('thunderstorms-day-overcast-rain', 'thunderstorms-night-overcast-rain'),
    99: ('thunderstorms-day-extreme-rain', 'thunderstorms-night-extreme-rain'),
}
UNKNOWN_ICON = 'not-available'

# Shape family for the drawn fallback, keyed by the same WMO codes.
FALLBACK_SHAPES = {
    0: 'clear', 1: 'clear', 2: 'partly', 3: 'cloudy', 45: 'fog', 48: 'fog',
    51: 'drizzle', 53: 'drizzle', 55: 'drizzle', 56: 'sleet', 57: 'sleet',
    61: 'rain', 63: 'rain', 65: 'rain', 66: 'sleet', 67: 'sleet',
    71: 'snow', 73: 'snow', 75: 'snow', 77: 'snow',
    80: 'showers', 81: 'showers', 82: 'showers', 85: 'snow', 86: 'snow',
    95: 'thunder', 96: 'thunder', 99: 'thunder',
}


def icon_name(code: Optional[int], is_day: bool = True) -> str:
    """Meteocons icon name for a WMO code."""
    pair = WMO_ICONS.get(int(code)) if code is not None else None
    if pair is None:
        return UNKNOWN_ICON
    return pair[0] if is_day else pair[1]


@lru_cache(maxsize=256)
def _load(name: str, size: int) -> Optional[Image.Image]:
    """Load and resize an icon, cached — every hourly slot asks for the same sizes."""
    path = ICON_DIR / f'{name}.png'
    try:
        with Image.open(path) as source:
            icon = source.convert('RGBA')
    except Exception as e:
        logger.debug(f'Icon {name} unavailable ({type(e).__name__}); using the drawn fallback')
        return None
    if icon.size != (size, size):
        icon = icon.resize((size, size), Image.LANCZOS)
    return icon


def paste(base: Image.Image, code: Optional[int], is_day: bool,
          cx: float, cy: float, size: float) -> bool:
    """
    Paste the icon for `code` centred on (cx, cy). Returns False when no asset
    was available, so the caller can fall back to drawing one.

    Meteocons artwork sits in a generous bounding box, so the pasted image is
    scaled up a little to look the same weight as the surrounding text.
    """
    box = max(int(size * 1.28), 8)
    icon = _load(icon_name(code, is_day), box)
    if icon is None:
        return False
    base.paste(icon, (int(cx - box / 2), int(cy - box / 2)), icon)
    return True


def draw(draw_obj, code: Optional[int], is_day: bool,
         cx: float, cy: float, size: float) -> None:
    """
    Fallback glyph built from primitives, for when the icon assets are missing.

    Deliberately plain: it should read correctly at a glance, not compete with
    the real icon set.
    """
    shape = FALLBACK_SHAPES.get(int(code), 'cloudy') if code is not None else 'cloudy'
    r = size / 2.0
    stroke = max(2, int(size * 0.055))

    def sun(x, y, radius, rays=True):
        draw_obj.ellipse([x - radius, y - radius, x + radius, y + radius], fill=ACCENT)
        if not rays:
            return
        for i in range(8):
            angle = math.radians(i * 45)
            inner, outer = radius * 1.35, radius * 1.85
            draw_obj.line([x + math.cos(angle) * inner, y + math.sin(angle) * inner,
                           x + math.cos(angle) * outer, y + math.sin(angle) * outer],
                          fill=ACCENT, width=stroke)

    def moon(x, y, radius):
        disc = Image.new('L', (int(radius * 2) + 4, int(radius * 2) + 4), 0)
        from PIL import ImageDraw
        mask = ImageDraw.Draw(disc)
        mask.ellipse([2, 2, radius * 2 + 2, radius * 2 + 2], fill=255)
        mask.ellipse([-radius * 0.5, radius * 0.15, radius * 1.35, radius * 1.85], fill=0)
        draw_obj.bitmap((x - radius - 2, y - radius - 2), disc, fill=SNOW)

    def cloud(x, y, width, colour=CLOUD):
        h = width * 0.52
        draw_obj.ellipse([x - width * 0.5, y - h * 0.28, x - width * 0.5 + h,
                          y - h * 0.28 + h], fill=colour)
        draw_obj.ellipse([x - width * 0.16, y - h * 0.62, x - width * 0.16 + h * 1.3,
                          y - h * 0.62 + h * 1.3], fill=colour)
        draw_obj.ellipse([x + width * 0.1, y - h * 0.2, x + width * 0.1 + h * 0.95,
                          y - h * 0.2 + h * 0.95], fill=colour)
        draw_obj.rounded_rectangle([x - width * 0.5, y + h * 0.18, x + width * 0.5,
                                    y + h * 0.62], radius=h * 0.22, fill=colour)

    def drops(x, y, count, length):
        for i in range(count):
            dx = x + (i - (count - 1) / 2.0) * size * 0.16
            draw_obj.line([dx + length * 0.35, y, dx, y + length], fill=RAIN, width=stroke)

    def flakes(x, y, count):
        for i in range(count):
            dx = x + (i - (count - 1) / 2.0) * size * 0.17
            rad = max(1.5, size * 0.045)
            draw_obj.ellipse([dx - rad, y - rad, dx + rad, y + rad], fill=SNOW)

    if shape == 'clear':
        sun(cx, cy, r * 0.44) if is_day else moon(cx, cy, r * 0.46)
    elif shape == 'partly':
        sun(cx + r * 0.3, cy - r * 0.34, r * 0.3) if is_day else moon(cx + r * 0.3, cy - r * 0.34, r * 0.28)
        cloud(cx - r * 0.12, cy + r * 0.18, size * 0.78)
    elif shape == 'cloudy':
        cloud(cx - r * 0.14, cy - r * 0.1, size * 0.66, colour=(196, 203, 215))
        cloud(cx + r * 0.14, cy + r * 0.22, size * 0.74)
    elif shape == 'fog':
        cloud(cx, cy - r * 0.24, size * 0.74)
        for i in range(3):
            y = cy + r * (0.34 + i * 0.22)
            inset = r * (0.1 + i * 0.12)
            draw_obj.line([cx - r * 0.72 + inset, y, cx + r * 0.72 - inset, y],
                          fill=MUTED, width=stroke)
    elif shape in ('drizzle', 'rain', 'showers'):
        if shape == 'showers' and is_day:
            sun(cx + r * 0.42, cy - r * 0.46, r * 0.24)
        cloud(cx, cy - r * 0.26, size * 0.76)
        drops(cx, cy + r * 0.34, 2 if shape == 'drizzle' else 3,
              size * (0.12 if shape == 'drizzle' else 0.2))
    elif shape == 'sleet':
        cloud(cx, cy - r * 0.26, size * 0.76)
        drops(cx - size * 0.09, cy + r * 0.34, 1, size * 0.16)
        flakes(cx + size * 0.11, cy + r * 0.46, 2)
    elif shape == 'snow':
        cloud(cx, cy - r * 0.26, size * 0.76)
        flakes(cx, cy + r * 0.42, 3)
    elif shape == 'thunder':
        cloud(cx, cy - r * 0.26, size * 0.76)
        draw_obj.polygon([
            (cx + r * 0.08, cy + r * 0.14), (cx - r * 0.18, cy + r * 0.62),
            (cx + r * 0.02, cy + r * 0.62), (cx - r * 0.1, cy + r * 0.96),
            (cx + r * 0.3, cy + r * 0.44), (cx + r * 0.08, cy + r * 0.44),
        ], fill=ACCENT)
    else:
        cloud(cx, cy, size * 0.76)


def render(base: Image.Image, draw_obj, code: Optional[int], is_day: bool,
           cx: float, cy: float, size: float) -> None:
    """Real icon if it's there, drawn glyph if it isn't."""
    if not paste(base, code, is_day, cx, cy, size):
        draw(draw_obj, code, is_day, cx, cy, size)


def available() -> Tuple[int, int]:
    """(icons found, icons referenced) — used by the startup log and the web UI."""
    referenced = {name for pair in WMO_ICONS.values() for name in pair} | {UNKNOWN_ICON}
    found = sum(1 for name in referenced if (ICON_DIR / f'{name}.png').is_file())
    return found, len(referenced)
