#!/usr/bin/env python3
"""
Web UI for the Frame TV dashboard.

Runs in a daemon thread alongside the sync loop and offers:
  - a live preview of the dashboard card on the current template
  - editing of the dashboard settings, applied without a restart
  - template image upload / removal
  - "sync now", which cuts the wait between sync cycles short

Deliberately unauthenticated, like the rest of this service: keep it on your
LAN, don't port-forward it.
"""

import io
import logging
import os
import re
import sys
import threading
import time
from pathlib import Path
from typing import Any, Dict, Optional, Tuple

from flask import Flask, jsonify, request, send_file, send_from_directory

import dashboard
import dashboard_settings

logger = logging.getLogger(__name__)

WEB_DIR = Path(__file__).parent / 'web'
ARTWORK_DIR = Path(os.getenv('ARTWORK_DIR', '/artwork'))
MAX_UPLOAD_BYTES = int(os.getenv('WEB_UI_MAX_UPLOAD_MB', '40')) * 1024 * 1024
PREVIEW_WIDTH = 1400
WEATHER_CACHE_TTL = 300  # seconds; Open-Meteo updates about every 15 minutes

# Templates are addressed by filename over HTTP, so restrict hard: no
# directories, no dotfiles, no traversal.
SAFE_NAME = re.compile(r'^[A-Za-z0-9][A-Za-z0-9 ._-]{0,120}$')

app = Flask(__name__, static_folder=None)
app.config['MAX_CONTENT_LENGTH'] = MAX_UPLOAD_BYTES

_weather_cache: Dict[Tuple, Tuple[float, Any]] = {}
_render_lock = threading.Lock()


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #

def _sync_module():
    """
    The running sync module, or None when the UI is started standalone.

    sync_artwork.py is normally the entry point, so it lives in sys.modules as
    '__main__' rather than under its own name; check both, and confirm it really
    is that module before trusting it.
    """
    for name in ('sync_artwork', '__main__'):
        module = sys.modules.get(name)
        if module is not None and hasattr(module, 'request_immediate_sync'):
            return module
    return None


def _template_dir(settings: Dict[str, Any]) -> Optional[Path]:
    """
    Directory that holds template images.

    A `background` pointing at a single file has no directory to manage, so
    uploads are refused in that case rather than writing somewhere surprising.
    """
    path = Path(settings['background']) if settings['background'] else None
    if path is None or path.is_file():
        return None
    return path


def _safe_template(settings: Dict[str, Any], name: str) -> Optional[Path]:
    directory = _template_dir(settings)
    if directory is None or not SAFE_NAME.match(name or ''):
        return None
    candidate = (directory / name).resolve()
    try:
        candidate.relative_to(directory.resolve())
    except ValueError:
        return None
    return candidate if candidate.is_file() else None


def _current_render() -> Optional[Path]:
    images = dashboard.existing_dashboard_images(ARTWORK_DIR)
    return images[-1] if images else None


def _weather_for(settings: Dict[str, Any]):
    """
    Weather for a preview, cached briefly.

    Without the cache, dragging the card-size slider would fire a weather
    request per preview — rude to a free API and slow for the user.
    """
    from dashboard_weather import fetch_weather

    key = (settings['latitude'], settings['longitude'], settings['timezone'],
           settings['units'], settings['time_format'], settings['location_name'],
           settings['forecast_hours'], settings['forecast_days'])
    hit = _weather_cache.get(key)
    now = time.time()
    if hit and now - hit[0] < WEATHER_CACHE_TTL:
        return hit[1]

    weather = fetch_weather(
        latitude=settings['latitude'],
        longitude=settings['longitude'],
        timezone=settings['timezone'],
        location_name=settings['location_name'],
        units=settings['units'],
        use_24h=settings['time_format'] != '12h',
        hours_ahead=max(settings['forecast_hours'], settings['card_hours']),
        forecast_days=settings['forecast_days'],
    )
    if weather is not None:
        _weather_cache[key] = (now, weather)
    return weather


# --------------------------------------------------------------------------- #
# routes
# --------------------------------------------------------------------------- #

@app.get('/')
def index():
    return send_from_directory(WEB_DIR, 'index.html')


@app.get('/api/status')
def api_status():
    settings = dashboard_settings.get()
    sync = _sync_module()
    render = _current_render()
    directory = _template_dir(settings)

    return jsonify({
        'settings': settings,
        'defaults': dashboard_settings.env_defaults(),
        'corners': list(dashboard_settings.CORNERS),
        'units': list(dashboard_settings.UNITS),
        'time_formats': list(dashboard_settings.TIME_FORMATS),
        'templates': [p.name for p in dashboard.available_templates(settings['background'])],
        'template_dir': str(directory) if directory else None,
        'can_upload': directory is not None,
        'sync': {
            'tv_ips': getattr(sync, 'TV_IPS', []),
            'interval_minutes': getattr(sync, 'SYNC_INTERVAL_MINUTES', None),
            'artwork_dir': str(ARTWORK_DIR),
            'current_image': getattr(sync, 'CURRENT_DASHBOARD_IMAGE', None) or (
                render.name if render else None),
            'rendered_at': int(render.stat().st_mtime) if render else None,
            'can_sync_now': bool(sync and getattr(sync, 'WAKE_EVENT', None) is not None),
        },
    })


@app.post('/api/settings')
def api_settings():
    patch = request.get_json(silent=True)
    if not isinstance(patch, dict) or not patch:
        return jsonify({'error': 'Expected a JSON object of settings to change.'}), 400
    try:
        settings = dashboard_settings.save(patch)
    except ValueError as e:
        return jsonify({'error': str(e)}), 400
    except OSError as e:
        logger.warning(f'Could not save settings: {e}')
        return jsonify({'error': f'Could not write settings: {e}'}), 500
    return jsonify({'settings': settings})


@app.get('/api/preview.png')
def api_preview():
    """Render the dashboard at preview size with the current (unsaved) settings."""
    settings = dashboard_settings.get()
    # Query parameters let the UI preview a change before saving it.
    for key in ('corner', 'card_scale', 'card_hours', 'units', 'time_format',
                'location_name', 'latitude', 'longitude', 'timezone', 'background'):
        if key in request.args:
            try:
                settings[key] = dashboard_settings.coerce(key, request.args[key])
            except ValueError as e:
                return jsonify({'error': str(e)}), 400

    if settings['latitude'] is None or settings['longitude'] is None:
        return jsonify({'error': 'Set a location first.'}), 400

    weather = _weather_for(settings)
    if weather is None:
        return jsonify({'error': 'Weather data is unavailable right now.'}), 502

    import datetime
    import zoneinfo

    from dashboard_render import render

    try:
        tz = zoneinfo.ZoneInfo(settings['timezone'])
    except Exception:
        tz = datetime.timezone.utc
    now = datetime.datetime.now(tz)
    clock = '%H:%M' if settings['time_format'] != '12h' else '%I:%M %p'

    # Preview at a fraction of the real resolution: same layout, far quicker.
    ratio = settings['height'] / settings['width']
    size = (PREVIEW_WIDTH, max(int(PREVIEW_WIDTH * ratio), 200))

    scratch = Path(os.getenv('TMPDIR', '/tmp')) / 'dashboard-preview.png'
    with _render_lock:
        render(
            weather,
            scratch,
            size=size,
            updated_text=now.strftime(clock).lstrip('0'),
            background=dashboard.pick_background(settings['background']),
            corner=settings['corner'],
            scale=settings['card_scale'],
            hours=settings['card_hours'],
        )
        data = scratch.read_bytes()

    response = send_file(io.BytesIO(data), mimetype='image/png')
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.get('/api/templates/<name>')
def api_template(name: str):
    settings = dashboard_settings.get()
    path = _safe_template(settings, name)
    if path is None:
        return jsonify({'error': 'No such template.'}), 404

    from PIL import Image, ImageOps

    with Image.open(path) as source:
        thumb = ImageOps.exif_transpose(source).convert('RGB')
        thumb.thumbnail((520, 520))
        buffer = io.BytesIO()
        thumb.save(buffer, format='JPEG', quality=82)
    buffer.seek(0)
    return send_file(buffer, mimetype='image/jpeg')


@app.post('/api/templates')
def api_template_upload():
    settings = dashboard_settings.get()
    directory = _template_dir(settings)
    if directory is None:
        return jsonify({'error': 'The template path is a single file, so there is no '
                                'folder to upload into. Point it at a directory first.'}), 400

    upload = request.files.get('file')
    if upload is None or not upload.filename:
        return jsonify({'error': 'No file was uploaded.'}), 400

    name = Path(upload.filename).name.replace('/', '_')
    if Path(name).suffix.lower() not in dashboard.TEMPLATE_FORMATS:
        return jsonify({'error': 'Use a JPG, PNG or WEBP image.'}), 400
    if not SAFE_NAME.match(name):
        # Keep the extension, replace anything awkward in the stem.
        stem = re.sub(r'[^A-Za-z0-9 ._-]', '_', Path(name).stem) or 'template'
        name = f'{stem[:100]}{Path(name).suffix.lower()}'

    try:
        directory.mkdir(parents=True, exist_ok=True)
        target = directory / name
        # Don't silently replace an existing template.
        counter = 2
        while target.exists():
            target = directory / f'{Path(name).stem}-{counter}{Path(name).suffix}'
            counter += 1
        upload.save(target)
    except OSError as e:
        return jsonify({'error': f'Could not save the file: {e}'}), 500

    # Verify it really is an image; a corrupt file would break every render.
    try:
        from PIL import Image
        with Image.open(target) as check:
            check.verify()
    except Exception:
        target.unlink(missing_ok=True)
        return jsonify({'error': 'That file is not a readable image.'}), 400

    logger.info(f'Template uploaded: {target.name}')
    return jsonify({'name': target.name})


@app.delete('/api/templates/<name>')
def api_template_delete(name: str):
    settings = dashboard_settings.get()
    path = _safe_template(settings, name)
    if path is None:
        return jsonify({'error': 'No such template.'}), 404
    try:
        path.unlink()
    except OSError as e:
        return jsonify({'error': f'Could not delete it: {e}'}), 500
    logger.info(f'Template deleted: {name}')
    return jsonify({'deleted': name})


@app.post('/api/sync-now')
def api_sync_now():
    sync = _sync_module()
    if sync is None or not sync.request_immediate_sync():
        return jsonify({'error': 'The sync loop is not running yet — try again in a moment.'}), 409
    return jsonify({'requested': True})


# --------------------------------------------------------------------------- #
# startup
# --------------------------------------------------------------------------- #

def start(host: str = '0.0.0.0', port: int = 8080) -> threading.Thread:
    """Start the web UI in a daemon thread so it never holds up shutdown."""
    # Werkzeug logs every request at INFO, which would drown the sync log.
    logging.getLogger('werkzeug').setLevel(logging.WARNING)

    def serve():
        try:
            app.run(host=host, port=port, threaded=True, debug=False,
                    use_reloader=False)
        except Exception as e:
            logger.error(f'Web UI stopped: {type(e).__name__}: {e}')

    thread = threading.Thread(target=serve, name='web-ui', daemon=True)
    thread.start()
    logger.info(f'Web UI listening on http://{host}:{port}')
    return thread
