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
import os
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

# How long a weather fetch stays good. Open-Meteo refreshes its data roughly
# every 15 minutes, so a 1-minute sync interval would ask 15 times for the same
# numbers. Cache them; the sync cadence and the fetch cadence are separate
# concerns.
WEATHER_TTL = int(os.getenv('WEATHER_CACHE_SECONDS', '600'))

# Default time each template image stays on screen when `background` is a
# folder; callers pass the configured value.
TEMPLATE_MINUTES = int(os.getenv('DASHBOARD_TEMPLATE_MINUTES', '60'))
_weather_cache: Optional[tuple] = None   # (fetched_at, key, weather)

# Signature of the last render. If nothing visible changed, the existing image
# is left in place: same filename means the sync finds nothing to upload or
# delete, so a minute-by-minute refresh costs the TV nothing until the card
# actually says something different.
_last_signature: Optional[str] = None


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


def pick_background(background: str, minutes: Optional[int] = None,
                    at: Optional[float] = None) -> Optional[Path]:
    """
    Choose the template image for a point in time.

    Rotation is a function of the clock, not of how often we render: a folder of
    templates advances every `minutes` regardless of the sync interval.
    That keeps the artwork changing at a sane pace even at a 1-minute refresh,
    and makes the choice reproducible — the web UI preview shows the same image
    the next render will use.

    Returns None when nothing is configured or the folder is empty, so the
    renderer falls back to its own gradient.
    """
    templates = available_templates(background)
    if not templates:
        if background:
            logger.warning(f'No template images found at {background}; using the plain background')
        return None
    if len(templates) == 1:
        return templates[0]

    span = max(minutes or TEMPLATE_MINUTES, 1) * 60
    slot = int((at if at is not None else time.time()) // span)
    return templates[slot % len(templates)]


def _fetch_cached(fetch, key: tuple, **kwargs):
    """fetch_weather(), memoised for WEATHER_TTL seconds."""
    global _weather_cache

    now = time.time()
    if _weather_cache is not None:
        fetched_at, cached_key, cached = _weather_cache
        if cached_key == key and now - fetched_at < WEATHER_TTL:
            logger.debug(f'Using weather data from {int(now - fetched_at)}s ago')
            return cached

    weather = fetch(**kwargs)
    if weather is not None:
        _weather_cache = (now, key, weather)
    return weather


def _signature(weather, updated_text: str, background: Optional[Path],
               size: tuple, corner: str, card_scale: float, card_hours: int,
               image_format: str) -> str:
    """Everything that ends up visible in the render, as a comparable string."""
    return repr((
        weather.location, weather.temperature, weather.feels_like, weather.condition,
        weather.code, weather.is_day, weather.today_high, weather.today_low,
        weather.humidity, weather.wind_speed, weather.temp_unit,
        [(h.label, h.temperature, h.precip_chance, h.code, h.is_day)
         for h in weather.hours[:card_hours]],
        updated_text, background.name if background else None,
        size, corner, card_scale, card_hours, image_format,
    ))


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
    show_updated: bool = True,
    template_minutes: int = 60,
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

    key = (latitude, longitude, timezone, location_name, units, time_format,
           hours_ahead, forecast_days, card_hours)
    weather = _fetch_cached(
        fetch_weather, key,
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
    updated_text = now.strftime(clock).lstrip('0') if show_updated else ''
    chosen_background = pick_background(background, template_minutes)

    # Nothing visible changed? Leave the existing render alone. The sync then
    # sees the same filename already on the TV and does nothing at all, which is
    # what makes a 1-minute interval affordable.
    global _last_signature
    signature = _signature(weather, updated_text, chosen_background, size, corner,
                           card_scale, card_hours, image_format)
    if signature == _last_signature and previous:
        logger.debug(f'Dashboard unchanged; keeping {previous[-1].name}')
        return previous[-1].name

    filename = f'{FILENAME_PREFIX}{int(time.time())}{suffix}'
    target = dest_dir / filename

    try:
        render(
            weather,
            target,
            size=size,
            date_text=now.strftime('%A, %d %B %Y'),
            updated_text=updated_text,
            background=chosen_background,
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

    _last_signature = signature
    logger.info(f'Rendered dashboard image {filename} ({target.stat().st_size // 1024} KB)')
    return filename
