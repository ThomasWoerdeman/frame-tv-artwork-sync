#!/usr/bin/env python3
"""
Dashboard image generation for the Frame TV.

Each refresh composites a small weather card onto a template image and writes
the result into the artwork directory under a timestamped name
(`dashboard-<epoch>.png`), removing the previous one. The timestamp matters:
the TV's art API has no "replace this image" call, and the sync logic keys off
filenames — a file whose name never changes would never be re-uploaded, so the
wall would keep showing the first render forever.
"""

import datetime
import logging
import time
import zoneinfo
from pathlib import Path
from typing import Optional

logger = logging.getLogger(__name__)

FILENAME_PREFIX = 'dashboard-'
# Renders may be JPEG or PNG; recognise both so a format change still cleans up
# the renders written before it.
RENDER_SUFFIXES = ('.jpg', '.jpeg', '.png')
TEMPLATE_FORMATS = {'.jpg', '.jpeg', '.png', '.webp'}

# Last template used, so a directory of templates rotates instead of the random
# walk repeating the same image two cycles running.
_last_background: Optional[str] = None


def is_dashboard_image(name: str) -> bool:
    return name.startswith(FILENAME_PREFIX) and name.lower().endswith(RENDER_SUFFIXES)


def existing_dashboard_images(dest_dir: Path) -> list:
    """Dashboard renders currently in the artwork directory, oldest first."""
    if not dest_dir.is_dir():
        return []
    return sorted(
        (p for p in dest_dir.iterdir() if p.is_file() and is_dashboard_image(p.name)),
        key=lambda p: p.name,
    )


def available_templates(background: str) -> list:
    """Template images at `background`, which may be a single file or a directory."""
    if not background:
        return []
    path = Path(background)
    if path.is_file():
        return [path]
    if path.is_dir():
        return sorted(p for p in path.iterdir()
                      if p.is_file() and p.suffix.lower() in TEMPLATE_FORMATS)
    return []


def pick_background(background: str) -> Optional[Path]:
    """
    Choose this cycle's template image, advancing through a directory in order.

    Returns None when nothing is configured or the folder is empty — the
    renderer then falls back to its own gradient so the dashboard still works
    before any template has been added.
    """
    global _last_background

    templates = available_templates(background)
    if not templates:
        if background:
            logger.warning(f'No template images found at {background}; using the plain background')
        return None

    names = [p.name for p in templates]
    if _last_background in names:
        chosen = templates[(names.index(_last_background) + 1) % len(templates)]
    else:
        chosen = templates[0]

    _last_background = chosen.name
    return chosen


def refresh(
    dest_dir: Path,
    latitude: float,
    longitude: float,
    timezone: str = 'UTC',
    location_name: str = '',
    units: str = 'metric',
    time_format: str = '24h',
    size: tuple = (3840, 2160),
    hours_ahead: int = 12,
    forecast_days: int = 5,
    background: str = '',
    corner: str = 'bottom-right',
    card_scale: float = 1.0,
    card_hours: int = 4,
    image_format: str = 'jpg',
) -> Optional[str]:
    """
    Render a new dashboard image and drop the old ones.

    Returns the filename of the current dashboard image, or None if there is no
    usable image at all. On a failed weather fetch the previous render is kept
    (and its name returned) so a network blip doesn't blank the wall or put an
    error card on it.
    """
    # Imported here so installations that only sync artwork never need Pillow
    # loaded, and so an import problem surfaces as a dashboard-only failure.
    from dashboard_weather import fetch_weather
    from dashboard_render import render

    previous = existing_dashboard_images(dest_dir)

    weather = fetch_weather(
        latitude=latitude,
        longitude=longitude,
        timezone=timezone,
        location_name=location_name,
        units=units,
        use_24h=time_format != '12h',
        hours_ahead=max(hours_ahead, card_hours),
        forecast_days=forecast_days,
    )

    if weather is None:
        if previous:
            logger.warning(
                f'Keeping the previous dashboard image ({previous[-1].name}); '
                f'weather data was unavailable this cycle'
            )
            return previous[-1].name
        logger.warning('No weather data and no previous dashboard image; nothing to show yet')
        return None

    try:
        tz = zoneinfo.ZoneInfo(timezone)
    except Exception:
        tz = datetime.timezone.utc
    now = datetime.datetime.now(tz)
    clock = '%H:%M' if time_format != '12h' else '%I:%M %p'

    suffix = '.png' if image_format == 'png' else '.jpg'
    filename = f'{FILENAME_PREFIX}{int(time.time())}{suffix}'
    target = dest_dir / filename

    try:
        render(
            weather,
            target,
            size=size,
            date_text=now.strftime('%A, %d %B %Y'),
            updated_text=now.strftime(clock).lstrip('0'),
            background=pick_background(background),
            corner=corner,
            scale=card_scale,
            hours=card_hours,
        )
    except Exception as e:
        logger.warning(f'Dashboard render failed: {type(e).__name__}: {e}')
        target.unlink(missing_ok=True)
        return previous[-1].name if previous else None

    for stale in previous:
        if stale.name != filename:
            try:
                stale.unlink()
            except OSError as e:
                logger.debug(f'Could not remove stale dashboard image {stale.name}: {e}')

    logger.info(f'Rendered dashboard image {filename} ({target.stat().st_size // 1024} KB)')
    return filename
