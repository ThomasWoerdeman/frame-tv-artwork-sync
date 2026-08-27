# Samsung Frame TV Artwork Sync

Automatically sync artwork from a local folder to Samsung Frame TVs using Docker.

**Image:** `ghcr.io/thomaswoerdeman/frame-tv-dashboard:latest` (linux/amd64, linux/arm64)

```bash
docker pull ghcr.io/thomaswoerdeman/frame-tv-dashboard:latest
```

Forked from [turley/frame-tv-artwork-sync](https://github.com/turley/frame-tv-artwork-sync)
([upstream image on Docker Hub](https://hub.docker.com/r/turley/frame-tv-artwork-sync)),
with dashboard mode and a web UI added.

## Features

- Dashboard mode: a small live weather card composited onto your own artwork
- Web UI for previewing the dashboard, placing the card and managing templates
- Sync artwork to one or multiple Frame TVs
- Automatic periodic sync (configurable interval)
- Auto-cleanup: removes images from TVs when deleted locally
- Persistent file tracking to avoid re-uploading
- Configurable matte/border style
- Slideshow control: preserve TV settings or override with custom interval/type
- Optional solar-based brightness adjustment using sun position and atmospheric modeling
- Manual brightness control with fixed values
- Skips offline TVs and continues syncing others
- Skips TVs not in art mode (e.g., when watching content via HDMI)
- Lightweight Alpine-based Docker image

## Quick Start

### Using Docker Compose (Recommended)

1. Download [docker-compose.yml](docker-compose.yml)
2. Create folders:
   ```bash
   mkdir -p artwork tokens templates config
   ```
3. Add your images to the artwork folder
4. Edit `docker-compose.yml` with your TV IP addresses
5. Run:
   ```bash
   docker-compose up -d
   ```

On first run, approve the connection on each TV when prompted. Tokens are saved for future use.

### Using Docker CLI

```bash
# Create folders
mkdir -p artwork tokens templates config

# Run container
docker run -d \
  --name frame-tv-sync \
  --restart unless-stopped \
  -e TV_IPS="192.168.1.100,192.168.1.101" \
  -e SYNC_INTERVAL_MINUTES="5" \
  -p 8080:8080 \
  -v ./artwork:/artwork \
  -v ./tokens:/tokens \
  -v ./templates:/templates \
  -v ./config:/config \
  ghcr.io/thomaswoerdeman/frame-tv-dashboard:latest
```

## Configuration

All settings are configured via environment variables:

| Variable                   | Description                                                                               | Default   |
| -------------------------- | ----------------------------------------------------------------------------------------- | --------- |
| `TV_IPS`                   | Comma-separated TV IP addresses (required)                                                | -         |
| `SYNC_INTERVAL_MINUTES`    | How often to sync (in minutes)                                                            | `5`       |
| `MATTE_STYLE`              | Border style (see [Matte Styles](#matte-styles) below)                                    | `none`    |
| `SLIDESHOW_ENABLED`        | Enable slideshow (true/false) - overrides TV settings if set                              | (unset)   |
| `SLIDESHOW_INTERVAL`       | Slideshow interval in minutes (use values supported by your TV model)                     | `15`      |
| `SLIDESHOW_TYPE`           | Slideshow type: `shuffle` or `sequential`                                                 | `shuffle` |
| `BRIGHTNESS`               | Manual brightness override (use values supported by your TV model, commonly 0-10 or 0-50) | (unset)   |
| `SOLAR_BRIGHTNESS_ENABLED` | Enable automatic solar-based brightness adjustment (true/false)                           | (unset)   |
| `LOCATION_LATITUDE`        | Latitude for solar calculations (e.g., 42.3601)                                           | -         |
| `LOCATION_LONGITUDE`       | Longitude for solar calculations (e.g., -71.0589)                                         | -         |
| `LOCATION_TIMEZONE`        | Timezone name (e.g., America/New_York)                                                    | `UTC`     |
| `BRIGHTNESS_MIN`           | Minimum brightness when sun is below horizon                                              | `2`       |
| `BRIGHTNESS_MAX`           | Maximum brightness if sun were at zenith (90°)                                            | `10`      |
| `DASHBOARD_ENABLED`        | Show a live weather card on the TV (true/false)                                            | (unset)   |
| `DASHBOARD_LOCATION_NAME`  | Name shown on the card                                                                    | timezone city |
| `DASHBOARD_BACKGROUND`     | Template image, or a folder of images to rotate through                                   | `/templates` |
| `DASHBOARD_CORNER`         | `top-left`, `top-right`, `bottom-left`, `bottom-right`                                     | `bottom-right` |
| `DASHBOARD_CARD_SCALE`     | Card size multiplier (0.4–2.5)                                                            | `1.0`     |
| `DASHBOARD_CARD_HOURS`     | Hours shown on the card (`0` to hide the strip)                                            | `4`       |
| `DASHBOARD_SHOW_UPDATED`   | Show the time on the card (see [Refresh rate](#refresh-rate))                              | `true`    |
| `DASHBOARD_TEMPLATE_MINUTES` | How long each template image stays on screen                                            | `60`      |
| `WEATHER_CACHE_SECONDS`    | How long weather data is reused between renders                                           | `600`     |
| `DASHBOARD_IMAGE_FORMAT`   | `jpg` (small, quick uploads) or `png` (lossless, ~5x larger)                                | `jpg`     |
| `DASHBOARD_JPEG_QUALITY`   | JPEG quality when the format is `jpg`                                                     | `92`      |
| `DASHBOARD_UNITS`          | `metric` (°C, km/h) or `imperial` (°F, mph)                                                | `metric`  |
| `DASHBOARD_TIME_FORMAT`    | `24h` or `12h`                                                                            | `24h`     |
| `DASHBOARD_WIDTH`          | Render width in pixels — match your TV panel                                              | `3840`    |
| `DASHBOARD_HEIGHT`         | Render height in pixels                                                                   | `2160`    |
| `DASHBOARD_FORECAST_HOURS` | Hours of forecast data to fetch                                                           | `12`      |
| `DASHBOARD_FORECAST_DAYS`  | Days of forecast data to fetch                                                            | `5`       |
| `WEATHER_TIMEOUT`          | Seconds to wait for the weather API                                                       | `15`      |
| `WEATHER_ICON_DIR`         | Folder holding the weather icon PNGs                                                      | `assets/weather-icons` |
| `CONFIG_DIR`               | Where the web UI stores settings                                                          | `/config` |
| `WEB_UI_ENABLED`           | Serve the web UI (true/false)                                                             | `true`    |
| `WEB_UI_HOST`              | Interface the web UI binds to                                                             | `0.0.0.0` |
| `WEB_UI_PORT`              | Web UI port                                                                               | `8080`    |
| `WEB_UI_MAX_UPLOAD_MB`     | Largest template image that can be uploaded                                               | `40`      |
| `REMOVE_UNKNOWN_IMAGES`    | Remove images from TV that aren't in the artwork folder (true/false)                      | `false`   |
| `AUTO_OFF_TIME`            | Time to turn off TVs in art mode (24-hour format, e.g., `22:00`)                          | (unset)   |
| `AUTO_OFF_GRACE_HOURS`     | Hours after `AUTO_OFF_TIME` to keep trying to turn off TVs                                | `2`       |

### Slideshow & Brightness Control

#### Slideshow Settings

**Default Behavior (no override variables set):**

- When images are added or removed during sync, the script preserves and restores your TV's current slideshow settings
- If no images change, slideshow settings are not modified

**Override Behavior (if any slideshow variable is set):**

- When images are added or removed during sync, the script applies slideshow settings from environment variables
- If you set `SLIDESHOW_ENABLED`, `SLIDESHOW_INTERVAL`, or `SLIDESHOW_TYPE`, all slideshow variables use defaults for any unset values
- If no images change, slideshow settings are not modified

**Note:** Slideshow interval values vary by TV model year. Common values include 3, 15, 60, 720, 1440 minutes. Check your TV's slideshow settings menu to see which intervals are supported by your specific model.

#### Brightness Control

**Manual Brightness:**

- Set `BRIGHTNESS` to a fixed value (commonly 0-10 or 0-50 depending on your TV model)
- Applied every sync run when set

**Solar-Based Brightness (Automatic):**

- Enable `SOLAR_BRIGHTNESS_ENABLED=true` to automatically adjust brightness based on sun position
- Requires `LOCATION_LATITUDE`, `LOCATION_LONGITUDE`, and `LOCATION_TIMEZONE`
- Set `BRIGHTNESS_MIN` (brightness when sun is below horizon) and `BRIGHTNESS_MAX` (brightness for sun at zenith)
- Brightness is calculated every sync run using physics-based atmospheric air mass model
- Uses Kasten-Young formula to model how sunlight intensity changes through the atmosphere
- Takes precedence over manual `BRIGHTNESS` setting when enabled

**Example Solar Setup:**

```bash
SOLAR_BRIGHTNESS_ENABLED=true
LOCATION_LATITUDE=42.3601
LOCATION_LONGITUDE=-71.0589
LOCATION_TIMEZONE=America/New_York
BRIGHTNESS_MIN=2
BRIGHTNESS_MAX=10
```

With this configuration (example for Boston, MA):

- At night (sun below horizon): brightness = 2
- At solar noon in summer (sun ~71°): brightness ≈ 7
- At solar noon in winter (sun ~24°): brightness ≈ 6
- At sunrise/sunset (sun near 0°): brightness = 2

**Testing Solar Brightness:**

To preview how brightness will change throughout the year at your location:

```bash
# Set your location variables
export LOCATION_LATITUDE=42.3601
export LOCATION_LONGITUDE=-71.0589
export LOCATION_TIMEZONE=America/New_York
export BRIGHTNESS_MIN=2
export BRIGHTNESS_MAX=10

# Run in test mode
python sync_artwork.py --test-solar
```

This displays hourly brightness levels for key solar positions (March Equinox, June Solstice, December Solstice), helping you verify your settings before deploying.

### Dashboard Mode

Dashboard mode draws a small weather card into one corner of a template image —
your own artwork stays the picture, the data sits quietly on top — and refreshes
it on every sync cycle. The card shows current temperature and conditions,
today's high and low, and the next few hours with rain chance.

Weather data comes from [Open-Meteo](https://open-meteo.com): no API key, no
account, no signup. The icons are [Meteocons](https://github.com/basmilius/meteocons)
by Bas Milius (MIT), vendored under `assets/weather-icons` and chosen per WMO
weather code with separate day and night artwork. Set your coordinates, point it at a template folder, and
turn it on:

```yaml
environment:
  TV_IPS: "192.168.1.100"
  SYNC_INTERVAL_MINUTES: "5"
  DASHBOARD_ENABLED: "true"
  DASHBOARD_LOCATION_NAME: "Amsterdam"
  DASHBOARD_BACKGROUND: "/templates"
  LOCATION_LATITUDE: "52.3676"
  LOCATION_LONGITUDE: "4.9041"
  LOCATION_TIMEZONE: "Europe/Amsterdam"
volumes:
  - ./templates:/templates
  - ./config:/config
```

`DASHBOARD_BACKGROUND` takes a single image or a folder. A folder rotates: each
refresh moves to the next image, so the artwork changes through the day while
the card stays put. With no template at all the card renders on a plain dark
background.

Each refresh writes `dashboard-<timestamp>.jpg` into the artwork folder, uploads
it, puts it on screen, and only then deletes the previous render from both the
folder and the TV. The name has to change every cycle: the TV's art API has no
"replace this image" call and the sync logic keys off filenames, so a fixed name
would upload once and never update again.

The order is deliberate — upload, select, *then* delete:

- Deleting first would leave the TV with nothing selected for a moment, and it
  falls back to its own default art.
- If the upload fails (a busy or briefly unreachable TV), the previous render is
  kept and displayed rather than deleted, so the frame always has something to
  show. The next cycle retries.
- Any `dashboard-*` image on the TV that isn't the current render is removed,
  even if a stale copy is still sitting in the artwork folder, so renders can't
  pile up on the TV.

One case this can't cover: if the TV's mapping file in `TOKEN_DIR` is lost, past
renders become unrecognised "unknown" images that only
`REMOVE_UNKNOWN_IMAGES=true` will clear. Keep the tokens volume persistent.

**Preview the card without a TV:**

```bash
docker compose run --rm frame-tv-sync python sync_artwork.py --test-dashboard /artwork/preview.png
```

Notes:

- Leave the slideshow off (`SLIDESHOW_ENABLED` unset or `false`). A slideshow
  rotates the TV away from the dashboard between refreshes.
- Static artwork in the same folder still syncs normally, but the dashboard is
  always the image selected for display.
- If the weather API is unreachable, the previous render stays on the wall and
  the next cycle tries again — no error card, no blank frame.
- Template rotation is on its own clock (`DASHBOARD_TEMPLATE_MINUTES`, default
  hourly), independent of the sync interval — so a fast refresh doesn't make the
  artwork flicker.

#### Refresh rate

`SYNC_INTERVAL_MINUTES=1` is fine. Two things keep it cheap:

- **Weather data is cached** (`WEATHER_CACHE_SECONDS`, default 10 minutes).
  Open-Meteo only refreshes every ~15 minutes, so a 1-minute sync would
  otherwise ask 10 times for identical numbers.
- **Unchanged renders are skipped.** Each render is compared against the last
  one; if nothing visible differs, the existing image stays and the sync finds
  nothing to upload, select, or delete. The TV is left completely alone.

That leaves one decision — the timestamp on the card:

| `DASHBOARD_SHOW_UPDATED` | At a 1-minute interval | Cost |
| --- | --- | --- |
| `true` (default) | The card is a live clock | One ~2 MB upload per minute |
| `false` | The card changes only when the weather does | Roughly one upload per 15 minutes |

If you want the clock, leave it on — a minute of upload traffic is small, and the
replace cycle keeps exactly one image on the TV. If you'd rather spare the TV's
flash, turn it off and you still get weather that's never more than a minute
stale. The toggle is in the web UI.

One caveat with a clock: a cycle takes ~10 seconds of work on top of the wait, so
the displayed time can occasionally skip a minute.

### Web UI

Browse to `http://<docker-host>:8080` for a preview of the dashboard and the
controls that shape it:

- **Preview** — the card rendered on the next template in rotation. Click a
  corner of the preview to move the card; drag the size slider to scale it.
- **Location and display** — name, coordinates, timezone, units, clock format
  and panel resolution.
- **Template images** — upload, review and delete the images the card is drawn
  on.
- **Sync to TV now** — cuts the wait between sync cycles short instead of
  waiting out the interval.
- **Status** — configured TVs, sync interval, which render is live and how old
  it is.

Changes are saved to `CONFIG_DIR/dashboard.json` and take effect on the next
refresh — no container restart. Environment variables remain the defaults;
anything set here overrides them, and deleting the file reverts to the
environment.

The UI is **unauthenticated**, like the rest of this service: keep it on your
LAN and don't port-forward it. Set `WEB_UI_ENABLED=false` to turn it off, or
drop the `ports:` mapping to keep it inside the Docker network.

### Image Cleanup Control

**`REMOVE_UNKNOWN_IMAGES`** - Controls whether the script removes images from your TV that aren't in your local artwork folder.

**Default behavior (`REMOVE_UNKNOWN_IMAGES=false` or unset):**

- Preserves any images already on the TV that were uploaded manually or before the script started tracking
- Only manages images that the script has uploaded
- Logs a warning when unknown images are detected, listing their content IDs

**When enabled (`REMOVE_UNKNOWN_IMAGES=true`):**

- Removes any images from the TV that aren't in your local artwork folder
- Ensures your TV only displays images from your synced collection
- Useful for maintaining a "clean slate" that exactly matches your local folder

### Auto-Off Control

**`AUTO_OFF_TIME`** - Automatically turn off TVs at a specific time, but only when they're in art mode. This feature only works on some Frame TV models.

This feature is useful when you want TVs to turn off at night but only if they're displaying art. If someone is actively watching the TV, it won't be interrupted.

**How it works:**

- Set `AUTO_OFF_TIME` to a time in 24-hour format (e.g., `22:00` for 10 PM)
- The script checks during each sync if the current time is within the turn-off window
- If a TV is in art mode during this window, it will be turned off after the sync completes
- TVs not in art mode (e.g., watching HDMI content) are left alone

**Grace period:**

- `AUTO_OFF_GRACE_HOURS` defines how long after `AUTO_OFF_TIME` the script will keep trying to turn off TVs
- Default is 2 hours, so if `AUTO_OFF_TIME=22:00`, it will try until midnight
- After the grace period ends, the script stops attempting to turn off TVs until the next day
- This handles cases where a TV wasn't in art mode at the exact off time

**Example setup:**

```bash
AUTO_OFF_TIME=22:00
AUTO_OFF_GRACE_HOURS=2
LOCATION_TIMEZONE=America/New_York
```

With this configuration:

- Starting at 10 PM (in your timezone), TVs in art mode will be turned off after sync
- If a TV is being used at 10 PM but returns to art mode by 11 PM, it will be turned off then
- After midnight, no turn-off attempts are made until the next day's 10 PM

**Note:** `LOCATION_TIMEZONE` is required for this feature to work correctly.

### Connection Tuning

Advanced knobs for the TV WebSocket connection. Defaults work for most setups; tune these only if you're seeing flaky connects, repeated re-auth prompts, or pairing failures.

| Variable                   | Description                                                                                              | Default |
| -------------------------- | -------------------------------------------------------------------------------------------------------- | ------- |
| `CONNECTION_TIMEOUT`       | WebSocket timeout (seconds) for normal connects with an existing token                                   | `10.0`  |
| `AUTH_TIMEOUT`             | WebSocket timeout (seconds) during first-time pairing (allows time for approval on the TV)               | `30.0`  |
| `KEEPALIVE_INTERVAL`       | Seconds between keepalive pings while waiting for the next sync (must be >= 1)                           | `60`    |
| `CONNECT_MAX_ATTEMPTS`     | Retry budget for connect errors (channel drops, transient failures). Excludes pairing retries.           | `3`     |
| `CHANNEL_DROP_RETRY_DELAY` | Seconds to wait between connect retries after a channel drop                                             | `3.0`   |
| `PAIRING_MAX_RETRIES`      | Retries while waiting for first-time pairing approval on the TV                                          | `5`     |
| `PAIRING_RETRY_DELAY`      | Seconds between pairing retries (sized for human reaction time)                                          | `5.0`   |
| `API_TIMEOUT`              | Seconds to wait for a general art-app request (slideshow status, etc.)                                   | `20`    |
| `CONTENT_LIST_TIMEOUT`     | Seconds to wait for the TV's list of uploaded images. Raise this if you have a large art collection.      | `45`    |

The keepalive ping prevents some Frame TVs from prompting for re-authentication between syncs. If you have a flaky network or notice repeated re-auth prompts, you can increase `PAIRING_MAX_RETRIES` or shorten `KEEPALIVE_INTERVAL`.

`CONTENT_LIST_TIMEOUT` matters more than it looks. The TV builds the whole list in one message, so the reply gets slower as your collection grows — a Frame with ~500 images takes about 10 seconds to send ~750KB. If it times out, the sync can't tell "slow" from "empty", so it skips that cycle rather than risk re-uploading your whole folder. If the logs show `Failed to get uploaded images from TV`, raise this value.

## Image Requirements

**Supported Formats:** JPEG, JPG, PNG

**Recommended Specs:**

- Resolution: 3840 x 2160 pixels (4K) for 43"+ TVs, 1920 x 1080 for 32" TVs
- Aspect ratio: 16:9
- File size: Under 20MB
- Color space: sRGB

## Matte Styles

Matte styles combine a border **style** with a **color** in the format `{style}_{color}`, or use `none` for no border.

**Available Styles:**
`modernthin`, `modern`, `modernwide`, `flexible`, `shadowbox`, `panoramic`, `triptych`, `mix`, `squares`

**Available Colors:**
`black`, `neutral`, `antique`, `warm`, `polar`, `sand`, `seafoam`, `sage`, `burgandy`, `navy`, `apricot`, `byzantine`, `lavender`, `redorange`, `skyblue`, `turquoise`

**Examples:**

- `shadowbox_polar` - shadowbox border in polar color
- `modern_apricot` - modern border in apricot color
- `flexible_antique` - flexible border in antique color
- `none` - no border (full screen)

## Local Testing

To test without Docker:

1. **Install dependencies:**

```bash
pip install git+https://github.com/NickWaterton/samsung-tv-ws-api.git pysolar
```

2. **Set up environment:**

```bash
# Copy and edit with your TV IP
cp .env.example .env

# Create directories
mkdir -p artwork tokens

# Add test images to artwork folder
```

3. **Run the script:**

```bash
export $(grep -v '^#' .env | xargs) && python sync_artwork.py
```

On first run, approve the connection on your TV. Press `Ctrl+C` to stop.

**Testing solar brightness calculations:**

If you've configured solar brightness settings, test them before running the full sync:

```bash
export $(grep -v '^#' .env | xargs) && python sync_artwork.py --test-solar
```

This shows hourly brightness predictions for key solar positions (March Equinox, June Solstice, December Solstice) without connecting to TVs.

**Dry run mode:**

Preview what changes would be made without actually modifying your TVs:

```bash
export $(grep -v '^#' .env | xargs) && python sync_artwork.py --dry-run
```

This connects to TVs to read their current state but won't upload, delete, or modify any settings.

## How It Works

### Slideshow Behavior

When the sync script uploads new images or deletes old ones:

1. **Syncs** the artwork (uploads new, deletes removed)
2. **Selects** an image to prevent the TV from showing default art (random image for shuffle mode, first image otherwise)
3. **Applies slideshow settings** based on your configuration:
   - If slideshow override variables are set (`SLIDESHOW_ENABLED`, `SLIDESHOW_INTERVAL`, or `SLIDESHOW_TYPE`), uses those settings
   - If no override variables are set, preserves and restores your TV's current slideshow settings

If no images change during a sync cycle, slideshow settings are not modified.

## Requirements

- Samsung Frame TV (2016+ models with Tizen OS)
- Docker and Docker Compose (or Python 3.9+ for local testing)
- Network access to TVs
- Dashboard mode: outbound HTTPS to `api.open-meteo.com`
- Web UI: a browser on the same network

## Troubleshooting

### Debug Logging

Set `LOG_LEVEL=DEBUG` in your environment to see detailed sync operations and TV responses.

## Credits

Built using [samsung-tv-ws-api](https://github.com/NickWaterton/samsung-tv-ws-api) by NickWaterton.

Weather data from [Open-Meteo](https://open-meteo.com) (CC BY 4.0 attribution
for the data, free for non-commercial use without an API key).

Weather icons are [Meteocons](https://github.com/basmilius/meteocons) by Bas
Milius, MIT licensed. The vendored subset and its licence are under
[assets/weather-icons](assets/weather-icons).

## AI Disclosure

This project was created with the assistance of AI tools.

## License

MIT
