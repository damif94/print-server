# Print Server API

HTTP server that receives files and sends them to a CUPS label printer (80×100mm).

**Base URL:** `http://<raspberry-ip>:8080`

---

## Authentication

All endpoints except `GET /` require:

```
X-API-Key: <api_key>
```

Missing or wrong key → `401 Unauthorized`.

---

## Endpoints

### GET /

Returns the web UI. No auth required.

---

### GET /health

```
X-API-Key: <key>
```

```json
{ "ok": true, "printer": "XP360B" }
```

---

### POST /detect

Detect the label type from a PDF (without converting or printing).

**Headers:**
| Header | Value |
|--------|-------|
| `Content-Type` | `application/pdf` |
| `X-Filename` | *(optional)* original filename — improves detection |

**Response 200:**
```json
{ "ok": true, "type": "mercadolibre" }
```

Possible `type` values: `mercadolibre`, `mlmelinet`, `gestionpost`, `shopify`.

---

### POST /convert

Convert a PDF to a label-sized PNG (638×799px). Useful for previewing before printing.

**Headers:**
| Header | Value |
|--------|-------|
| `Content-Type` | `application/pdf` |
| `X-Filename` | *(optional)* original filename |
| `X-Label-Type` | *(optional)* override auto-detection |

**Query params:**
| Param | Description |
|-------|-------------|
| `type` | Override label type (e.g. `?type=shopify`) |

**Response 200:** `image/png` binary  
**Response header:** `X-Label-Type: <detected_type>`

---

### POST /label

Generate a KAI DECO label image from text fields (no PDF needed). Returns a PNG.

**Headers:** `Content-Type: application/json`

**Body:**
```json
{
  "name":    "Gonzalo Cámara",
  "address": "Av. Gonzalo Ramírez 1329 Apto 1909",
  "city":    "11100 Montevideo",
  "country": "Uruguay",
  "phone":   "099 238 500",
  "notes":   "Entregar en portería",
  "order":   "1234"
}
```

`name` is required. All other fields are optional.

**Response 200:** `image/png` binary (638×799px)

---

### POST /print

Send a file to the printer. Accepts PDF, PNG, or JPEG.

**Headers:**
| Header | Required | Value |
|--------|----------|-------|
| `Content-Type` | Yes | `application/pdf`, `image/png`, or `image/jpeg` |
| `X-Filename` | No | Original filename (PDFs only — aids type detection) |
| `X-Label-Type` | No | Override label type for PDFs |

**Query params:**
| Param | Description |
|-------|-------------|
| `type` | Override label type for PDFs (e.g. `?type=gestionpost`) |

**Behavior by content type:**

| Type | Server action |
|------|--------------|
| `application/pdf` | Auto-detects label type → converts to PNG → rotates 180° → prints |
| `image/png` / `image/jpeg` | Resizes to fit 638×799px → rotates 180° → prints |

**Response 200:**
```json
{
  "ok": true,
  "message": "print_submitted",
  "printer": "XP360B",
  "content_type": "application/pdf",
  "detected_label_type": "mercadolibre",
  "lp_output": "request id is XP360B-12 (1 file(s))"
}
```

**Error responses:**

| Status | `error` | Cause |
|--------|---------|-------|
| 400 | `invalid_content_type` | Unsupported Content-Type |
| 400 | `empty_body` | No data sent |
| 401 | `unauthorized` | Missing or wrong API key |
| 411 | `missing_content_length` | No Content-Length header |
| 500 | `print_failed` | `lp` rejected the job (includes `stdout`/`stderr`) |
| 500 | `conversion_failed` | PDF could not be converted |
| 500 | `server_error` | Unexpected error (includes `detail`) |

---

## Typical flows

### Preview + print (frontend / n8n two-step)

```
POST /convert   →   receive PNG   →   show preview
POST /print     →   send PNG      →   printer
```

### Single-shot from n8n or script

```
POST /print  (with PDF)   →   detect + convert + print
```

---

## Examples

### curl — detect type

```bash
curl -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/pdf" \
  -H "X-Filename: labels.pdf" \
  --data-binary "@labels.pdf" \
  http://192.168.0.100:8080/detect
```

### curl — convert PDF to PNG

```bash
curl -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/pdf" \
  --data-binary "@labels.pdf" \
  http://192.168.0.100:8080/convert \
  --output etiqueta.png
```

### curl — print PDF in one shot

```bash
curl -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/pdf" \
  --data-binary "@labels.pdf" \
  http://192.168.0.100:8080/print
```

### curl — generate label from text

```bash
curl -X POST \
  -H "X-API-Key: YOUR_KEY" \
  -H "Content-Type: application/json" \
  -d '{"name":"Gonzalo Cámara","address":"Av. Gonzalo Ramírez 1329","city":"Montevideo","phone":"099 238 500"}' \
  http://192.168.0.100:8080/label \
  --output etiqueta.png
```

### Python — single-shot PDF print

```python
import requests

with open("labels.pdf", "rb") as f:
    res = requests.post(
        "http://192.168.0.100:8080/print",
        headers={"X-API-Key": "YOUR_KEY", "Content-Type": "application/pdf"},
        data=f.read(),
    )
print(res.json())
```

---

## Label specs

| Property | Value |
|----------|-------|
| Size | 80 × 100 mm |
| Resolution | 203 DPI |
| Output px | 638 × 799 px |
| Printer | XP360B (CUPS) |

## System dependencies

```bash
sudo apt install poppler-utils    # required for pdf2image (PDF rendering)
pip install -r requirements.txt   # Pillow, pdf2image, pdfplumber
```
