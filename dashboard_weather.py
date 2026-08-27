#!/usr/bin/env python3
"""
Weather data source for the Frame TV dashboard.

Uses Open-Meteo (https://open-meteo.com), which needs no API key and no
account. Coordinates come from the same LOCATION_LATITUDE / LOCATION_LONGITUDE
/ LOCATION_TIMEZONE variables the solar-brightness feature already uses.
"""

import json
import logging
import os
import socket
import time
import urllib.error
import urllib.parse
import time
import urllib.request
from dataclasses import dataclass, field
from typing import List, Optional

logger = logging.getLogger(__name__)

WEATHER_API_HOST = urllib.parse.urlparse(
    os.getenv('WEATHER_API_URL', 'https://api.open-meteo.com/v1/forecast')).hostname

WEATHER_API_URL = os.getenv('WEATHER_API_URL', 'https://api.open-meteo.com/v1/forecast')
WEATHER_TIMEOUT = float(os.getenv('WEATHER_TIMEOUT', '15'))

# Why the last fetch failed, and when one last worked. Kept here so the web UI
# can show the actual cause instead of a bare "unavailable" — the usual causes
# are container DNS and blocked egress, which look identical from the outside.
LAST_ERROR: Optional[str] = None
LAST_SUCCESS: Optional[float] = None   # epoch seconds of the last good fetch
LAST_SUCCESS: Optional[float] = None

# WMO weather interpretation codes -> short label. Icons are chosen from the
# same codes in dashboard_icons.
# https://open-meteo.com/en/docs — the "Weather variable documentation" table.
WMO_CODES = {
    0: 'Clear',
    1: 'Mainly clear',
    2: 'Partly cloudy',
    3: 'Overcast',
    45: 'Fog',
    48: 'Freezing fog',
    51: 'Light drizzle',
    53: 'Drizzle',
    55: 'Heavy drizzle',
    56: 'Freezing drizzle',
    57: 'Freezing drizzle',
    61: 'Light rain',
    63: 'Rain',
    65: 'Heavy rain',
    66: 'Freezing rain',
    67: 'Freezing rain',
    71: 'Light snow',
    73: 'Snow',
    75: 'Heavy snow',
    77: 'Snow grains',
    80: 'Light showers',
    81: 'Showers',
    82: 'Heavy showers',
    85: 'Snow showers',
    86: 'Snow showers',
    95: 'Thunderstorm',
    96: 'Thunderstorm',
    99: 'Severe thunderstorm',
}


def describe_code(code: Optional[int]) -> str:
    """Human-readable label for a WMO code."""
    if code is None:
        return 'Unknown'
    return WMO_CODES.get(int(code), f'Code {code}')


@dataclass
class HourSlot:
    label: str          # e.g. "14:00" or "2 PM"
    temperature: float
    precip_chance: int
    code: int           # WMO weather code
    is_day: bool


@dataclass
class DaySlot:
    label: str          # e.g. "Mon"
    high: float
    low: float
    precip_chance: int
    code: int           # WMO weather code


@dataclass
class Weather:
    """Everything the renderer needs, already unit-converted and formatted."""
    location: str
    temperature: float
    feels_like: float
    condition: str
    code: int           # WMO weather code
    humidity: int
    wind_speed: float
    wind_unit: str
    temp_unit: str
    today_high: float
    today_low: float
    sunrise: str
    sunset: str
    is_day: bool
    hours: List[HourSlot] = field(default_factory=list)
    days: List[DaySlot] = field(default_factory=list)


def _fmt_time(iso: str, use_24h: bool) -> str:
    """Format an Open-Meteo local ISO timestamp ('2026-08-27T14:00') as a clock time."""
    try:
        hour, minute = iso.split('T')[1].split(':')[:2]
        hour_i = int(hour)
    except (IndexError, ValueError):
        return iso
    if use_24h:
        return f'{hour_i:02d}:{minute}'
    suffix = 'AM' if hour_i < 12 else 'PM'
    display = hour_i % 12 or 12
    # Whole hours read better bare ("2 PM"); sunrise/sunset need the minutes.
    if minute == '00':
        return f'{display} {suffix}'
    return f'{display}:{minute} {suffix}'


def _weekday(iso_date: str) -> str:
    import datetime
    try:
        return datetime.date.fromisoformat(iso_date).strftime('%a')
    except ValueError:
        return iso_date


def fetch_weather(
    latitude: float,
    longitude: float,
    timezone: str = 'auto',
    location_name: str = '',
    units: str = 'metric',
    use_24h: bool = True,
    hours_ahead: int = 12,
    forecast_days: int = 5,
) -> Optional[Weather]:
    """
    Fetch current conditions plus hourly and daily forecast.

    Returns None on any network/parse failure — callers should keep showing the
    previous dashboard rather than putting an error card on the wall.
    """
    metric = units.lower() != 'imperial'
    params = {
        'latitude': f'{latitude:.4f}',
        'longitude': f'{longitude:.4f}',
        'timezone': timezone or 'auto',
        'current': 'temperature_2m,relative_humidity_2m,apparent_temperature,'
                   'is_day,weather_code,wind_speed_10m',
        'hourly': 'temperature_2m,precipitation_probability,weather_code,is_day',
        'daily': 'weather_code,temperature_2m_max,temperature_2m_min,'
                 'precipitation_probability_max,sunrise,sunset',
        # Open-Meteo needs 2 days of hourly data to cover a 12h window near midnight.
        'forecast_days': str(max(forecast_days, 2)),
        'temperature_unit': 'celsius' if metric else 'fahrenheit',
        'wind_speed_unit': 'kmh' if metric else 'mph',
        'precipitation_unit': 'mm' if metric else 'inch',
    }
    url = f'{WEATHER_API_URL}?{urllib.parse.urlencode(params)}'

    global LAST_ERROR, LAST_SUCCESS

    try:
        request = urllib.request.Request(url, headers={'User-Agent': 'frame-tv-dashboard'})
        with urllib.request.urlopen(request, timeout=WEATHER_TIMEOUT) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as e:
        LAST_ERROR = f'{WEATHER_API_HOST} returned HTTP {e.code}'
        logger.warning(f'Weather fetch failed: {LAST_ERROR}')
        return None
    except urllib.error.URLError as e:
        LAST_ERROR = _explain(e.reason)
        logger.warning(f'Weather fetch failed: {LAST_ERROR}')
        return None
    except (OSError, ValueError) as e:
        LAST_ERROR = f'{type(e).__name__}: {e}'
        logger.warning(f'Weather fetch failed: {LAST_ERROR}')
        return None

    try:
        weather = _parse(payload, location_name, metric, use_24h, hours_ahead, forecast_days)
    except (KeyError, IndexError, TypeError, ValueError) as e:
        LAST_ERROR = f'unexpected response format ({type(e).__name__}: {e})'
        logger.warning(f'Weather response could not be parsed: {LAST_ERROR}')
        return None

    LAST_ERROR = None
    LAST_SUCCESS = time.time()
    return weather


def _explain(reason) -> str:
    """
    Turn a urllib failure into something a user can act on.

    In a container these are nearly always one of two things: the name doesn't
    resolve (no DNS configured on the container's network) or the connection is
    refused/times out (egress blocked upstream).
    """
    text = str(reason)
    lowered = text.lower()
    if 'name or service not known' in lowered or 'nodename nor servname' in lowered \
            or 'temporary failure in name resolution' in lowered:
        return (f'cannot resolve {WEATHER_API_HOST} — the container has no working DNS. '
                f'On unRAID, check the container\'s network mode and DNS settings.')
    if 'timed out' in lowered or 'timeout' in lowered:
        return (f'connection to {WEATHER_API_HOST} timed out after '
                f'{WEATHER_TIMEOUT:.0f}s — outbound HTTPS may be blocked.')
    if 'refused' in lowered:
        return f'connection to {WEATHER_API_HOST} was refused — outbound HTTPS may be blocked.'
    if 'certificate' in lowered:
        return f'TLS verification failed for {WEATHER_API_HOST}: {text}'
    if 'unreachable' in lowered:
        return f'{WEATHER_API_HOST} is unreachable from the container: {text}'
    return f'{WEATHER_API_HOST} could not be reached: {text}'


def _explain(error) -> str:
    """
    Turn a fetch failure into something a person can act on.

    Accepts an exception or a URLError.reason, which may itself be an exception
    or a bare string.
    """
    text = str(error)
    if isinstance(error, urllib.error.HTTPError):
        return (f'The weather service answered HTTP {error.code}. If this is 429, '
                f'the free API limit was hit — raise WEATHER_CACHE_SECONDS.')
    if isinstance(error, (socket.gaierror,)) or 'Name or service not known' in text \
            or 'Temporary failure in name resolution' in text or 'nodename nor servname' in text:
        return (f'{WEATHER_API_HOST} could not be resolved: this container has no working DNS. '
                f'Check its network mode and DNS settings.')
    if 'CERTIFICATE' in text.upper() or 'SSL:' in text.upper():
        return (f'TLS failed ({text}). Usually a wrong system clock or an intercepting proxy '
                f'whose certificate is not installed.')
    if isinstance(error, socket.timeout) or 'timed out' in text:
        return (f'The request timed out after {WEATHER_TIMEOUT:.0f}s. Outbound HTTPS may be '
                f'blocked, or WEATHER_TIMEOUT is too short for this connection.')
    if isinstance(error, urllib.error.URLError):
        reason = error.reason
        if isinstance(reason, socket.gaierror) or 'Name or service not known' in str(reason) \
                or 'Temporary failure in name resolution' in str(reason):
            return ('api.open-meteo.com could not be resolved: this container has no working '
                    'DNS. On Docker, check the container\'s network and DNS settings.')
        if 'CERTIFICATE' in str(reason).upper() or 'SSL' in str(reason).upper():
            return (f'TLS failed ({reason}). Usually a wrong system clock or an intercepting '
                    f'proxy without its certificate installed.')
        return f'Could not reach api.open-meteo.com: {reason}'
    return f'{type(error).__name__}: {text}'


def _parse(payload, location_name, metric, use_24h, hours_ahead, forecast_days) -> Weather:
    current = payload['current']
    hourly = payload['hourly']
    daily = payload['daily']

    label = describe_code(current.get('weather_code'))

    # Find the first hourly index at or after the current hour. Open-Meteo
    # returns whole days of hourly data, so the list starts at 00:00 today.
    now_hour = current['time'][:13]  # '2026-08-27T14'
    times = hourly['time']
    start = next((i for i, t in enumerate(times) if t[:13] >= now_hour), 0)

    hours = []
    for i in range(start, min(start + hours_ahead, len(times))):
        hours.append(HourSlot(
            label=_fmt_time(times[i], use_24h),
            temperature=hourly['temperature_2m'][i],
            precip_chance=int(hourly['precipitation_probability'][i] or 0),
            code=hourly['weather_code'][i],
            is_day=bool(hourly['is_day'][i]),
        ))

    days = []
    for i in range(min(forecast_days, len(daily['time']))):
        days.append(DaySlot(
            label='Today' if i == 0 else _weekday(daily['time'][i]),
            high=daily['temperature_2m_max'][i],
            low=daily['temperature_2m_min'][i],
            precip_chance=int(daily['precipitation_probability_max'][i] or 0),
            code=daily['weather_code'][i],
        ))

    return Weather(
        location=location_name or payload.get('timezone', '').split('/')[-1].replace('_', ' '),
        temperature=current['temperature_2m'],
        feels_like=current['apparent_temperature'],
        condition=label,
        code=current.get('weather_code'),
        humidity=int(current.get('relative_humidity_2m') or 0),
        wind_speed=current.get('wind_speed_10m') or 0.0,
        wind_unit='km/h' if metric else 'mph',
        temp_unit='C' if metric else 'F',
        today_high=daily['temperature_2m_max'][0],
        today_low=daily['temperature_2m_min'][0],
        sunrise=_fmt_time(daily['sunrise'][0], use_24h),
        sunset=_fmt_time(daily['sunset'][0], use_24h),
        is_day=bool(current.get('is_day', 1)),
        hours=hours,
        days=days,
    )
