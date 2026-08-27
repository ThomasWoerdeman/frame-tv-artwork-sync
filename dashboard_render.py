#!/usr/bin/env python3
"""
Renders the dashboard image shown on the Frame TV.

The output is a template/background image with a small frosted weather card in
one corner — the picture stays the picture, the data sits quietly on top of it.
Everything is drawn with Pillow primitives (icons included), so the container
needs no browser and no icon assets.
"""

import logging
import math
import os
from pathlib import Path
from typing import Optional, Sequence, Tuple

from PIL import Image, ImageDraw, ImageFilter, ImageFont, ImageOps

import dashboard_icons
from dashboard_weather import Weather

logger = logging.getLogger(__name__)

# Palette. The card sits on unknown imagery, so text is white-ish on a dark
# scrim and accents stay muted enough not to fight the artwork.
TEXT = (255, 255, 255)
MUTED = (206, 212, 224)
DIM = (166, 175, 191)
RAIN = (130, 186, 236)
SCRIM = (12, 15, 22)          # card tint, applied at CARD_OPACITY
CARD_OPACITY = 150            # 0-255 over the blurred backdrop
CARD_BLUR = 0.012             # blur radius as a fraction of card height

# Fallback background when no template image is configured or readable.
BG_TOP = (14, 18, 30)
BG_BOTTOM = (7, 9, 16)

CORNERS = ('top-left', 'top-right', 'bottom-left', 'bottom-right')
JPEG_QUALITY = int(os.getenv('DASHBOARD_JPEG_QUALITY', '92'))

# Font candidates, in preference order: Alpine (container), then macOS/Linux
# desktops so `--test-dashboard` works on a dev machine.
FONT_CANDIDATES = {
    'regular': [
        '/usr/share/fonts/dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/ttf-dejavu/DejaVuSans.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf',
        '/System/Library/Fonts/Supplemental/Arial.ttf',
        '/Library/Fonts/Arial.ttf',
    ],
    'bold': [
        '/usr/share/fonts/dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/ttf-dejavu/DejaVuSans-Bold.ttf',
        '/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf',
        '/System/Library/Fonts/Supplemental/Arial Bold.ttf',
        '/Library/Fonts/Arial Bold.ttf',
    ],
}


def _load_font(weight: str, size: int) -> ImageFont.FreeTypeFont:
    for path in FONT_CANDIDATES.get(weight, []):
        try:
            return ImageFont.truetype(path, max(size, 8))
        except OSError:
            continue
    logger.warning(f'No TrueType font found for weight {weight!r}; text will be unstyled')
    return ImageFont.load_default(max(size, 8))


class Fonts:
    """Font set scaled to the card height, so any card size stays proportional."""

    def __init__(self, unit: float) -> None:
        self.temp = _load_font('regular', int(unit * 0.36))
        self.unit_mark = _load_font('regular', int(unit * 0.13))
        self.condition = _load_font('regular', int(unit * 0.115))
        self.meta = _load_font('regular', int(unit * 0.095))
        self.label = _load_font('bold', int(unit * 0.072))
        self.hour_label = _load_font('regular', int(unit * 0.070))
        self.hour_temp = _load_font('regular', int(unit * 0.098))


def _gradient(size: Tuple[int, int]) -> Image.Image:
    """Vertical gradient, used when no template image is available."""
    width, height = size
    strip = Image.new('RGB', (1, height))
    pixels = strip.load()
    for y in range(height):
        t = y / max(height - 1, 1)
        pixels[0, y] = tuple(
            int(BG_TOP[c] + (BG_BOTTOM[c] - BG_TOP[c]) * t) for c in range(3)
        )
    return strip.resize(size, Image.BILINEAR)


def load_background(path: Optional[Path], size: Tuple[int, int]) -> Image.Image:
    """
    Load a template image and cover-fit it to `size` (scale up, centre-crop),
    falling back to the gradient if it can't be read.
    """
    if path is None:
        return _gradient(size)
    try:
        with Image.open(path) as source:
            image = ImageOps.exif_transpose(source).convert('RGB')
            return ImageOps.fit(image, size, method=Image.LANCZOS, centering=(0.5, 0.5))
    except Exception as e:
        logger.warning(f'Could not use background {path}: {type(e).__name__}: {e}')
        return _gradient(size)


def _tracked(draw: ImageDraw.ImageDraw, xy, text: str, font, fill, tracking: float = 0,
             anchor: str = 'la') -> None:
    """Draw text with letter spacing. Only 'la'/'ls'/'lm' anchors make sense here."""
    x, y = xy
    for char in text:
        draw.text((x, y), char, font=font, fill=fill, anchor=anchor)
        x += draw.textlength(char, font=font) + tracking


def _temp(value: Optional[float]) -> str:
    return '--' if value is None else f'{round(value):d}'


def _card_box(size: Tuple[int, int], corner: str, scale: float,
              hours: int) -> Tuple[int, int, int, int]:
    """Card rectangle for the requested corner, as (x0, y0, x1, y1)."""
    width, height = size
    card_w = width * 0.30 * scale
    card_h = height * (0.185 if hours else 0.125) * scale
    # Clamp so an over-large scale can't push the card off the panel.
    card_w = min(card_w, width * 0.8)
    card_h = min(card_h, height * 0.8)
    inset_x = width * 0.045
    inset_y = height * 0.055

    x0 = inset_x if corner.endswith('left') else width - inset_x - card_w
    y0 = inset_y if corner.startswith('top') else height - inset_y - card_h
    return int(x0), int(y0), int(x0 + card_w), int(y0 + card_h)


def _frost(base: Image.Image, box: Tuple[int, int, int, int], radius: int) -> None:
    """Blur and tint the area under the card so text stays readable on any image."""
    x0, y0, x1, y1 = box
    region = base.crop(box)
    blur = max(1, int((y1 - y0) * CARD_BLUR))
    region = region.filter(ImageFilter.GaussianBlur(blur))

    tint = Image.new('RGBA', region.size, SCRIM + (CARD_OPACITY,))
    region = Image.alpha_composite(region.convert('RGBA'), tint)

    # Rounded corners: paste through a mask so the artwork stays untouched outside.
    mask = Image.new('L', region.size, 0)
    ImageDraw.Draw(mask).rounded_rectangle([0, 0, region.size[0] - 1, region.size[1] - 1],
                                          radius=radius, fill=255)
    base.paste(region.convert('RGB'), (x0, y0), mask)

    # Hairline edge to separate the card from busy imagery.
    edge = Image.new('RGBA', base.size, (0, 0, 0, 0))
    ImageDraw.Draw(edge).rounded_rectangle([x0, y0, x1 - 1, y1 - 1], radius=radius,
                                          outline=(255, 255, 255, 46),
                                          width=max(1, int((y1 - y0) * 0.005)))
    base.paste(Image.alpha_composite(base.convert('RGBA'), edge).convert('RGB'), (0, 0))


def _draw_card(base: Image.Image, weather: Weather, box, updated_text: str,
               hours: int) -> None:
    x0, y0, x1, y1 = box
    card_h = y1 - y0
    fonts = Fonts(card_h)
    draw = ImageDraw.Draw(base)

    pad = card_h * 0.11
    header_h = card_h * (0.17 if hours else 0.22)
    body_h = (card_h - header_h) * (0.62 if hours else 1.0)
    body_top = y0 + header_h

    # Header: location, and the time this data was read.
    _tracked(draw, (x0 + pad, y0 + header_h * 0.62),
             weather.location.upper(), fonts.label, MUTED,
             tracking=card_h * 0.012, anchor='lm')
    if updated_text:
        draw.text((x1 - pad, y0 + header_h * 0.62), updated_text,
                  font=fonts.label, fill=DIM, anchor='rm')

    # Body: icon, temperature, condition and today's range.
    mid = body_top + body_h * 0.5
    icon_size = card_h * 0.40
    dashboard_icons.render(base, draw, weather.code, weather.is_day,
                           x0 + pad + icon_size * 0.5, mid, icon_size)

    temp_x = x0 + pad + icon_size + card_h * 0.05
    temp = _temp(weather.temperature)
    draw.text((temp_x, mid), temp, font=fonts.temp, fill=TEXT, anchor='lm')
    temp_w = draw.textlength(temp, font=fonts.temp)
    draw.text((temp_x + temp_w + card_h * 0.02, mid - card_h * 0.08),
              f'°{weather.temp_unit}', font=fonts.unit_mark, fill=MUTED, anchor='lm')

    draw.text((x1 - pad, mid - body_h * 0.19), weather.condition,
              font=fonts.condition, fill=TEXT, anchor='rm')
    draw.text((x1 - pad, mid + body_h * 0.21),
              f'H {_temp(weather.today_high)}°   L {_temp(weather.today_low)}°',
              font=fonts.meta, fill=MUTED, anchor='rm')

    if not hours or not weather.hours:
        return

    # Footer: the next few hours, with a rain-chance percentage where it matters.
    slots = list(weather.hours)[:hours]
    strip_top = body_top + body_h
    draw.line([x0 + pad, strip_top, x1 - pad, strip_top], fill=(255, 255, 255, 40),
              width=max(1, int(card_h * 0.004)))

    inner_w = (x1 - pad) - (x0 + pad)
    slot_w = inner_w / len(slots)
    label_y = strip_top + (y1 - strip_top) * 0.34
    temp_y = strip_top + (y1 - strip_top) * 0.68

    icon_size = card_h * 0.15
    for index, hour in enumerate(slots):
        cx = x0 + pad + slot_w * (index + 0.5)
        draw.text((cx, label_y), hour.label, font=fonts.hour_label, fill=DIM, anchor='mm')

        icon_cx = cx - slot_w * 0.34
        dashboard_icons.render(base, draw, hour.code, hour.is_day, icon_cx, temp_y, icon_size)

        value = f'{_temp(hour.temperature)}°'
        value_x = icon_cx + icon_size * 0.66
        draw.text((value_x, temp_y), value, font=fonts.hour_temp, fill=TEXT, anchor='lm')

        # Rain chance sits at the right edge of the slot — but only when it fits
        # without touching the temperature. More hours means narrower slots, and
        # a collision reads as garbage ("27°31%") rather than as two numbers.
        if hour.precip_chance >= 20:
            pct = f'{hour.precip_chance}%'
            pct_right = cx + slot_w * 0.49
            pct_left = pct_right - draw.textlength(pct, font=fonts.hour_label)
            value_right = value_x + draw.textlength(value, font=fonts.hour_temp)
            if pct_left > value_right + card_h * 0.03:
                draw.text((pct_right, temp_y), pct, font=fonts.hour_label,
                          fill=RAIN, anchor='rm')


def render(weather: Weather, path: Path, size: Tuple[int, int] = (3840, 2160),
           date_text: str = '', updated_text: str = '',
           background: Optional[Path] = None, corner: str = 'bottom-right',
           scale: float = 1.0, hours: int = 4) -> Path:
    """
    Composite the weather card onto the template image and save to `path`.

    `date_text` is accepted for callers that want it but is not drawn — the card
    is deliberately minimal; `updated_text` carries the freshness signal.
    """
    if corner not in CORNERS:
        logger.warning(f'Unknown corner {corner!r}; using bottom-right')
        corner = 'bottom-right'

    base = load_background(background, size)
    box = _card_box(size, corner, scale, hours)
    radius = int((box[3] - box[1]) * 0.075)

    _frost(base, box, radius)
    _draw_card(base, weather, box, updated_text, hours)

    path.parent.mkdir(parents=True, exist_ok=True)
    if path.suffix.lower() in ('.jpg', '.jpeg'):
        # A 4K PNG of a photographic template runs to ~10 MB and takes ten
        # seconds to push to the TV. JPEG at this quality is a tenth of that,
        # and subsampling=0 keeps the card's small text crisp.
        base.save(path, format='JPEG', quality=JPEG_QUALITY, subsampling=0, optimize=True)
    else:
        base.save(path, format='PNG', optimize=True)
    logger.debug(f'Rendered dashboard to {path} ({path.stat().st_size // 1024} KB)')
    return path
