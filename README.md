# Viks TV Stream Monitor

Continuously scans public Viks TV channel pages for direct stream URLs already exposed in page HTML/player configuration and writes an M3U playlist.

## Run (Termux / Linux)

```bash
pkg update
pkg install python
pip install -r requirements.txt
python viks_parser.py
```

One scan only:

```bash
python viks_parser.py --once
```

## Configuration

- `VIKS_BASE_URL` (default `https://live.viks.tv`)
- `VIKS_CATALOG_URL` (default `https://live.viks.tv/tv3/`)
- `REFRESH_SECONDS` pause between complete scans (default `1`)
- `MAX_WORKERS` parallel requests (default `4`)
- `HTTP_TIMEOUT` request timeout in seconds (default `20`)

Example: `REFRESH_SECONDS=5 MAX_WORKERS=3 python viks_parser.py`

A full scan may take longer than the pause. This is not a guarantee that each channel is refreshed exactly once per second. Frequent scans can overload the site or trigger rate limits; increase the interval if errors occur.

## Output

- `playlist.m3u` — generated playlist
- `channels.json` — channel names and current discovered URLs
- `debug.html` — downloaded catalog HTML for troubleshooting

The monitor extracts only direct `.m3u8` / `.mpd` URLs or video source URLs exposed in fetched page HTML. It does not execute protected player code or bypass DRM, login, CAPTCHA, paywalls, expiring-token protections, or other access controls. Use only streams you are authorized to access and redistribute.
