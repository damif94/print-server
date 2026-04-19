# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## What this is

A minimal Python HTTP print server that accepts PDF/JPG/PNG files and sends them to a CUPS label printer via `lp`. Deployed as a systemd service on Linux.

## Running

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
python server.py
```

## Configuration

All config lives in `config.py` (hardcoded, no env vars):
- `PRINTER_NAME` — CUPS printer name (currently `XP360B`)
- `API_KEY` — auth key sent as `X-API-Key` header
- `LABEL_WIDTH_PX` / `LABEL_HEIGHT_PX` — label dimensions at 203 DPI (80×100mm)
- `LABEL_MEDIA` — CUPS media string passed to `lp -o media=`

## API

All endpoints require `X-API-Key` header (except `GET /`).

| Method | Path | Notes |
|--------|------|-------|
| GET | `/` | Serves `index.html` |
| GET | `/health` | Returns `{"ok": true, "printer": "..."}` |
| POST | `/print` | Body: raw PDF/JPG/PNG; `Content-Type` required |

## Architecture

- `server.py` — starts `HTTPServer` with `PrintHandler`
- `handlers.py` — `PrintHandler(BaseHTTPRequestHandler)`: auth, file receive, image resize, `lp` subprocess call
- `config.py` — all constants
- `logging_utils.py` — structured JSON logging to stdout (consumed by `journalctl`)

**Print flow:** receive raw body → write to `tempfile.mkdtemp` → if image, resize to label bounds preserving aspect ratio via Pillow → call `lp -d PRINTER_NAME -o media=LABEL_MEDIA <file>` → clean up temp dir.

## Testing manually

```bash
# Health
curl -H "X-API-Key: agustinmanya1994" http://localhost:8080/health

# Print a file
curl -X POST -H "X-API-Key: agustinmanya1994" -H "Content-Type: image/png" \
  --data-binary "@file.png" http://localhost:8080/print
```

## Systemd (production)

```bash
sudo systemctl restart print-api   # after code changes
sudo systemctl status print-api --no-pager
journalctl -u print-api -f         # live logs
```
