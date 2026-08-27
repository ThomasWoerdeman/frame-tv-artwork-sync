#!/usr/bin/env python3
"""
Dashboard settings: environment defaults, overridable at runtime.

Environment variables set the defaults (so a plain Docker setup needs nothing
else). The web UI writes overrides to CONFIG_DIR/dashboard.json, which win over
the environment and are re-read on every render — no container restart to move
the card to another corner.
"""

import json
import logging
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)

CONFIG_DIR = Path(os.getenv('CONFIG_DIR', '/config'))
SETTINGS_FILE = CONFIG_DIR / 'dashboard.json'

CORNERS = ('top-left', 'top-right', 'bottom-left', 'bottom-right')
UNITS = ('metric', 'imperial')
IMAGE_FORMATS = ('jpg', 'png')
TIME_FORMATS = ('24h', '12h')

# Fields the UI may change, with their type and bounds. Anything not listed here
# is not settable at runtime.
FIELDS: Dict[str, Tuple[str, Any]] = {
    'enabled': ('bool', None),
    'location_name': ('str', None),
    'latitude': ('float', (-90.0, 90.0)),
    'longitude': ('float', (-180.0, 180.0)),
    'timezone': ('str', None),
    'units': ('choice', UNITS),
    'time_format': ('choice', TIME_FORMATS),
    'width': ('int', (640, 7680)),
    'height': ('int', (360, 4320)),
    'forecast_hours': ('int', (1, 48)),
    'forecast_days': ('int', (1, 16)),
    'background': ('str', None),
    'corner': ('choice', CORNERS),
    'card_scale': ('float', (0.4, 2.5)),
    'card_hours': ('int', (0, 8)),
    'image_format': ('choice', IMAGE_FORMATS),
}


def _env_float(name: str) -> Optional[float]:
    raw = os.getenv(name, '')
    try:
        return float(raw) if raw else None
    except ValueError:
        logger.warning(f'{name}={raw!r} is not a number; ignoring')
        return None


def env_defaults() -> Dict[str, Any]:
    """Settings as configured by the environment, before any UI overrides."""
    return {
        'enabled': os.getenv('DASHBOARD_ENABLED', '').lower() in ('true', '1', 'yes'),
        'location_name': os.getenv('DASHBOARD_LOCATION_NAME', ''),
        'latitude': _env_float('LOCATION_LATITUDE'),
        'longitude': _env_float('LOCATION_LONGITUDE'),
        'timezone': os.getenv('LOCATION_TIMEZONE', 'UTC'),
        'units': os.getenv('DASHBOARD_UNITS', 'metric').lower(),
        'time_format': os.getenv('DASHBOARD_TIME_FORMAT', '24h').lower(),
        'width': int(os.getenv('DASHBOARD_WIDTH', '3840')),
        'height': int(os.getenv('DASHBOARD_HEIGHT', '2160')),
        'forecast_hours': int(os.getenv('DASHBOARD_FORECAST_HOURS', '12')),
        'forecast_days': int(os.getenv('DASHBOARD_FORECAST_DAYS', '5')),
        'background': os.getenv('DASHBOARD_BACKGROUND', '/templates'),
        'corner': os.getenv('DASHBOARD_CORNER', 'bottom-right').lower(),
        'card_scale': float(os.getenv('DASHBOARD_CARD_SCALE', '1.0')),
        'card_hours': int(os.getenv('DASHBOARD_CARD_HOURS', '4')),
        'image_format': os.getenv('DASHBOARD_IMAGE_FORMAT', 'jpg').lower(),
    }


def coerce(key: str, value: Any) -> Any:
    """
    Coerce and range-check one field, raising ValueError if it can't be used.

    Both the settings file and the UI go through this, so a hand-edited file
    can't put the renderer into a state the UI would have refused.
    """
    if key not in FIELDS:
        raise ValueError(f'unknown setting {key!r}')
    kind, bound = FIELDS[key]

    if kind == 'bool':
        if isinstance(value, bool):
            return value
        return str(value).lower() in ('true', '1', 'yes', 'on')
    if kind == 'str':
        return '' if value is None else str(value)
    if kind == 'choice':
        text = str(value).lower()
        if text not in bound:
            raise ValueError(f'{key} must be one of {", ".join(bound)}')
        return text
    if kind in ('int', 'float'):
        if value in (None, ''):
            if key in ('latitude', 'longitude'):
                return None
            raise ValueError(f'{key} is required')
        number = int(value) if kind == 'int' else float(value)
        low, high = bound
        if not low <= number <= high:
            raise ValueError(f'{key} must be between {low} and {high}')
        return number
    raise ValueError(f'unhandled field kind {kind!r}')


def load_overrides() -> Dict[str, Any]:
    """Read the overrides file, ignoring anything unusable rather than failing."""
    if not SETTINGS_FILE.is_file():
        return {}
    try:
        raw = json.loads(SETTINGS_FILE.read_text())
    except (OSError, ValueError) as e:
        logger.warning(f'Could not read {SETTINGS_FILE}: {type(e).__name__}: {e}')
        return {}
    if not isinstance(raw, dict):
        logger.warning(f'{SETTINGS_FILE} does not contain an object; ignoring it')
        return {}

    clean = {}
    for key, value in raw.items():
        try:
            clean[key] = coerce(key, value)
        except ValueError as e:
            logger.warning(f'Ignoring setting from {SETTINGS_FILE}: {e}')
    return clean


def get() -> Dict[str, Any]:
    """Effective settings: environment defaults with file overrides applied."""
    settings = env_defaults()
    settings.update(load_overrides())
    return settings


def save(patch: Dict[str, Any]) -> Dict[str, Any]:
    """
    Persist a patch of overrides and return the new effective settings.

    Raises ValueError with a UI-presentable message if any field is invalid;
    nothing is written in that case.
    """
    validated = {key: coerce(key, value) for key, value in patch.items()}

    overrides = load_overrides()
    overrides.update(validated)

    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    # Write via a temp file in the same directory so a crash mid-write can't
    # leave a half-written settings file behind.
    handle, temp_path = tempfile.mkstemp(dir=str(CONFIG_DIR), suffix='.tmp')
    try:
        with os.fdopen(handle, 'w') as out:
            json.dump(overrides, out, indent=2, sort_keys=True)
            out.write('\n')
        os.replace(temp_path, SETTINGS_FILE)
    except Exception:
        Path(temp_path).unlink(missing_ok=True)
        raise

    logger.info(f'Saved dashboard settings: {", ".join(sorted(validated))}')
    return get()
