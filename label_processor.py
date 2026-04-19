"""
Label processing: type detection, PDF→image conversion, text label generation.

System dependency required: poppler-utils  (for pdf2image)
"""

import io
import re
from PIL import Image, ImageDraw, ImageFont

# ── Label dimensions ──────────────────────────────────────────────────────────
PRINTER_DPI = 203
OUT_W = round(80  / 25.4 * PRINTER_DPI)   # 638 px
OUT_H = round(100 / 25.4 * PRINTER_DPI)   # 799 px
PAD   = round(70  / 945  * OUT_W)         # 47 px

# ── Per-type crop config (percentages of rendered page size) ──────────────────
LABEL_CONFIGS = {
    "mercadolibre": {"page": 0, "cx": 0, "cy": 0, "cw": 36, "ch": 79},
    "mlmelinet":    {"page": 0, "cx": 0, "cy": 0, "cw": 35, "ch": 78},
    "gestionpost":  {"page": 0, "cx": 0, "cy": 0, "cw": 48, "ch": 51},
    "shopify":      None,   # handled via text extraction → drawCleanLabel
}

LABEL_TYPE_NAMES = {
    "mercadolibre": "Mercado Libre",
    "mlmelinet":    "ML Melinet",
    "gestionpost":  "GestionPost",
    "shopify":      "Shopify",
}

_KEYWORDS = {
    "gestionpost":  ["gestionpost", "entregamos felicidad", "ursec:", "gestionpost.com.uy"],
    "shopify":      ["facturar a", "pedido #", "packing slip", "kai deco"],
    "mlmelinet":    ["melinet", "ues sa", "ues111", "xmv01", "uesm"],
    "mercadolibre": ["mercado libre", "envio:", "venta:", "zona ", "flex"],
}

_DEPTOS = {
    "AR": "Artigas",    "CA": "Canelones",   "CL": "Cerro Largo",  "CO": "Colonia",
    "DU": "Durazno",    "FS": "Flores",      "FD": "Florida",      "LA": "Lavalleja",
    "MA": "Maldonado",  "MO": "Montevideo",  "PA": "Paysandú",     "RN": "Río Negro",
    "RV": "Rivera",     "RO": "Rocha",       "SA": "Salto",        "SJ": "San José",
    "SO": "Soriano",    "TA": "Tacuarembó",  "TT": "Treinta y Tres",
}


# ── Type detection ────────────────────────────────────────────────────────────

def detect_type(pdf_bytes: bytes, filename: str = "") -> str:
    """Detect label type. Filename heuristic first, then PDF text content."""
    name = filename.lower()
    if "packing_slip" in name or "shopify" in name:
        return "shopify"
    if "gestion" in name:
        return "gestionpost"

    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            text = (pdf.pages[0].extract_text() or "").lower()
        for tipo, keywords in _KEYWORDS.items():
            if any(k in text for k in keywords):
                return tipo
    except Exception:
        pass

    return "mercadolibre"


# ── Font helpers ──────────────────────────────────────────────────────────────

def _load_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    bold_suffix  = "-Bold" if bold else ""
    reg_suffix   = "Bold"  if bold else "Regular"
    candidates = [
        f"/usr/share/fonts/truetype/dejavu/DejaVuSans{bold_suffix}.ttf",
        f"/usr/share/fonts/truetype/liberation/LiberationSans-{reg_suffix}.ttf",
        f"/usr/share/fonts/truetype/freefont/FreeSans{'Bold' if bold else ''}.ttf",
        f"/usr/share/fonts/truetype/noto/NotoSans-{reg_suffix}.ttf",
    ]
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            pass
    return ImageFont.load_default()


# ── Text label generation ─────────────────────────────────────────────────────

def generate_text_label(
    name: str,
    address: str = "",
    city: str = "",
    country: str = "Uruguay",
    phone: str = "",
    notes: str = "",
    order: str = "",
) -> Image.Image:
    """Generate a KAI DECO label image from text fields."""
    img  = Image.new("RGB", (OUT_W, OUT_H), "white")
    draw = ImageDraw.Draw(img)
    max_w = OUT_W - PAD * 2

    # Border
    draw.rectangle([8, 8, OUT_W - 8, OUT_H - 8], outline="#dddddd", width=3)

    # ── Header ──
    HEADER_H = round(OUT_H * 0.18)
    draw.rectangle([0, 0, OUT_W, HEADER_H], fill="black")
    f_hdr = _load_font(round(HEADER_H * 0.55), bold=True)
    txt   = "KAI DECO"
    bbox  = draw.textbbox((0, 0), txt, font=f_hdr)
    draw.text(
        ((OUT_W - (bbox[2] - bbox[0])) // 2, (HEADER_H - (bbox[3] - bbox[1])) // 2),
        txt, fill="white", font=f_hdr,
    )

    # ── Phone zone reserved at bottom ──
    phone_sz   = round(OUT_H * 0.075)
    phone_h    = round(phone_sz * 1.35)
    bottom_pad = round(OUT_H * 0.035)
    phone_y    = OUT_H - bottom_pad - phone_h
    phone_zone = phone_h + round(OUT_H * 0.055)

    y = HEADER_H + round(OUT_H * 0.04)

    def _wrap(text: str, font) -> list:
        words = text.split()
        lines, cur = [], ""
        for w in words:
            test = (cur + " " + w) if cur else w
            if draw.textbbox((0, 0), test, font=font)[2] > max_w and cur:
                lines.append(cur)
                cur = w
            else:
                cur = test
        if cur:
            lines.append(cur)
        return lines or [text]

    def write_line(text: str, size: int, bold: bool = False, color: str = "#000"):
        nonlocal y
        if not text or not text.strip():
            return
        f = _load_font(size, bold=bold)
        for line in _wrap(text, f):
            draw.text((PAD, y), line, fill=color, font=f)
            y += round(size * 1.35)

    def draw_sep(color: str, margin: int):
        nonlocal y
        draw.line([(PAD, y), (OUT_W - PAD, y)], fill=color, width=1)
        y += margin

    # ── Content ──
    name_sz = round(OUT_H * 0.082)
    addr_sz = round(OUT_H * 0.064)

    if order:
        write_line(f"Pedido #{order}", round(OUT_H * 0.042), color="#aaaaaa")

    write_line(name, name_sz, bold=True)
    y += round(OUT_H * 0.01)
    draw_sep("#e0e0e0", round(OUT_H * 0.018))

    if address:
        write_line(address, addr_sz, color="#222222")
        y += round(OUT_H * 0.006)
    if city:
        write_line(city, addr_sz, color="#222222")
    if country and country.strip().lower() not in ("uruguay", ""):
        write_line(country, addr_sz, color="#222222")

    if notes and notes.strip():
        y += round(OUT_H * 0.02)
        draw_sep("#f0f0f0", round(OUT_H * 0.012))
        write_line("Nota: " + notes, round(OUT_H * 0.055), color="#555555")

    # ── Phone at bottom ──
    if phone and phone.strip():
        sep_y = phone_y - round(OUT_H * 0.022)
        draw.line([(PAD, sep_y), (OUT_W - PAD, sep_y)], fill="black", width=3)
        f_ph = _load_font(phone_sz, bold=True)
        draw.text((PAD, phone_y), f"Tel: {phone}", fill="black", font=f_ph)

    return img


# ── Shopify data extraction ───────────────────────────────────────────────────

def _extract_shopify_data(pdf_bytes: bytes) -> dict | None:
    """Extract shipping address from a Shopify packing slip PDF."""
    try:
        import pdfplumber
        with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
            page   = pdf.pages[0]
            words  = page.extract_words(x_tolerance=3, y_tolerance=3)
            page_w = float(page.width)
            page_h = float(page.height)
        TOL = page_h * 0.009

        # Column divider: x of "FACTURAR A"
        facturar = [w for w in words if "facturar" in w["text"].lower()]
        col_div  = facturar[0]["x0"] if facturar else page_w * 0.45

        # "ENVIAR A" header position
        enviar = [w for w in words if "enviar" in w["text"].lower()]
        if not enviar:
            return None
        enviar_y = enviar[0]["top"]

        # Left-column words below header
        left = [w for w in words if w["top"] > enviar_y + 5 and w["x0"] < col_div]

        # Group into lines by y proximity
        lines: list[dict] = []
        for w in sorted(left, key=lambda x: (x["top"], x["x0"])):
            if lines and abs(w["top"] - lines[-1]["top"]) < TOL:
                lines[-1]["items"].append(w["text"])
            else:
                lines.append({"top": w["top"], "items": [w["text"]]})

        STOP = {"artículos", "articulos", "notas", "gracias", "cantidad"}
        addr = []
        for ln in lines:
            txt = " ".join(ln["items"]).strip()
            if any(txt.lower().startswith(s) for s in STOP):
                break
            if txt:
                addr.append(txt)

        if not addr:
            return None

        name = addr[0]

        def is_uy_phone(s: str) -> bool:
            c = re.sub(r"[\s\-(). ]", "", s)
            return bool(
                re.match(r"^(\+?598)?0?9\d{7,8}$", c) or
                re.match(r"^(\+?598)?2\d{7}$", c) or
                re.match(r"^(\+?598)?[34]\d{7}$", c)
            )

        phone   = next((l for l in addr if is_uy_phone(l)), "")
        country = next((l for l in addr if re.match(r"^(uruguay|argentina|brasil|chile|paraguay|peru|mexico)", l, re.I)), "")
        rest    = [l for l in addr if l not in (name, phone, country)]

        city_idx = next(
            (i for i, l in enumerate(rest) if
             re.search(r"UY-", l, re.I) or
             re.search(r"\b(montevideo|canelones|maldonado|salto|paysand[uú]|rivera|colonia|florida|treinta|rocha|artigas|durazno|flores|lavalleja|soriano|tacuaremb[oó]|cerro largo)\b", l, re.I)),
            None,
        )
        if city_idx is not None:
            city_raw     = rest[city_idx]
            street_lines = [rest[i] for i in range(len(rest)) if i != city_idx]
        else:
            street_lines = rest[:-1] if len(rest) > 1 else []
            city_raw     = rest[-1] if rest else ""

        city = re.sub(r"\bUY-([A-Z]+)\b", lambda m: _DEPTOS.get(m.group(1).upper(), ""), city_raw, flags=re.I)
        city = re.sub(r"\b\d{5}\b", "", city).strip().strip(",").strip()

        all_text = " ".join(" ".join(ln["items"]) for ln in lines)
        order_m  = re.search(r"pedido\s*#\s*(\d+)", all_text, re.I)

        return {
            "name":    name,
            "address": " ".join(street_lines),
            "city":    city,
            "phone":   phone,
            "notes":   "",
            "order":   order_m.group(1) if order_m else "",
        }
    except Exception:
        return None


# ── PDF → label image ─────────────────────────────────────────────────────────

def pdf_to_label_image(pdf_bytes: bytes, label_type: str) -> Image.Image:
    """Convert a PDF page to a label-sized PIL image (OUT_W × OUT_H)."""
    if label_type == "shopify":
        data = _extract_shopify_data(pdf_bytes)
        if not data or not data.get("name"):
            raise ValueError('No se encontró la sección "ENVIAR A" en el PDF de Shopify.')
        return generate_text_label(**data)

    from pdf2image import convert_from_bytes
    cfg   = LABEL_CONFIGS.get(label_type) or LABEL_CONFIGS["mercadolibre"]
    pages = convert_from_bytes(pdf_bytes, dpi=300, first_page=cfg["page"] + 1, last_page=cfg["page"] + 1)
    page  = pages[0]
    w, h  = page.size
    sx    = int(cfg["cx"] / 100 * w)
    sy    = int(cfg["cy"] / 100 * h)
    sw    = int(cfg["cw"] / 100 * w)
    sh    = int(cfg["ch"] / 100 * h)
    return page.crop((sx, sy, sx + sw, sy + sh)).resize((OUT_W, OUT_H), Image.LANCZOS)
