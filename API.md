# Print Server API

HTTP server that receives files and sends them to a CUPS label printer (80×100mm).

**Base URL:** `http://<raspberry-ip>:8080`

---

## Authentication

All endpoints (except `GET /`) require the header:

```
X-API-Key: <api_key>
```

Missing or wrong key → `401 Unauthorized`.

---

## Endpoints

### GET /

Returns the web UI (`index.html`). No auth required.

---

### GET /health

Check if the server and printer are reachable.

**Headers:** `X-API-Key`

**Response 200:**
```json
{ "ok": true, "printer": "XP360B" }
```

---

### POST /print

Send a file to print.

**Headers:**
| Header | Required | Value |
|--------|----------|-------|
| `X-API-Key` | Yes | API key |
| `Content-Type` | Yes | `image/png`, `image/jpeg`, or `application/pdf` |
| `Content-Length` | Yes | File size in bytes |

**Body:** raw binary file contents.

**Behavior:**
- PNG/JPEG: auto-resized to fit 80×100mm (639×799px at 203 DPI), rotated 180°, aspect ratio preserved.
- PDF: sent to printer as-is.

**Response 200:**
```json
{
  "ok": true,
  "message": "print_submitted",
  "printer": "XP360B",
  "detected_content_type": "image/png",
  "lp_output": "request id is XP360B-12 (1 file(s))"
}
```

**Error responses:**

| Status | `error` field | Cause |
|--------|--------------|-------|
| 400 | `invalid_content_type` | Content-Type not supported |
| 400 | `empty_body` / `empty_file` | No file data sent |
| 401 | `unauthorized` | Missing or wrong API key |
| 411 | `missing_content_length` | No Content-Length header |
| 500 | `print_failed` | `lp` rejected the job (includes `stdout`/`stderr`) |
| 500 | `server_error` | Unexpected server error (includes `detail`) |

All error responses follow the shape:
```json
{ "ok": false, "error": "<error_code>", ... }
```

---

## Examples

### curl

```bash
# Health check
curl -H "X-API-Key: YOUR_KEY" http://192.168.0.100:8080/health

# Print a PNG
curl -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: image/png" \
  --data-binary "@label.png" \
  http://192.168.0.100:8080/print

# Print a PDF
curl -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/pdf" \
  --data-binary "@document.pdf" \
  http://192.168.0.100:8080/print
```

### JavaScript (fetch)

```js
async function printLabel(fileBlob, mimeType) {
  const res = await fetch("http://192.168.0.100:8080/print", {
    method: "POST",
    headers: {
      "X-API-Key": "YOUR_KEY",
      "Content-Type": mimeType,
    },
    body: fileBlob,
  });
  return res.json();
}
```

### Python

```python
import requests

def print_label(file_path: str, mime_type: str):
    with open(file_path, "rb") as f:
        data = f.read()
    res = requests.post(
        "http://192.168.0.100:8080/print",
        headers={
            "X-API-Key": "YOUR_KEY",
            "Content-Type": mime_type,
        },
        data=data,
    )
    return res.json()

print_label("label.png", "image/png")
```

---

## Label specs

| Property | Value |
|----------|-------|
| Size | 80 × 100 mm |
| Resolution | 203 DPI |
| Max px (W×H) | 639 × 799 px |
| Printer | XP360B (CUPS) |
