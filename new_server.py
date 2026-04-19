from flask import Flask, request, send_file, jsonify
from pdf2image import convert_from_bytes
from PIL import Image, ImageDraw, ImageFont
import io, os, subprocess, tempfile, hmac, re

try:
    from pypdf import PdfReader
    PYPDF_OK = True
except ImportError:
    PYPDF_OK = False

app = Flask(__name__)

# ── CONFIGURACIÓN ──────────────────────────────────────────────────────────────
API_KEY          = os.environ.get('API_KEY', 'kai-deco-2025-clave-secreta')
NOMBRE_IMPRESORA = os.environ.get('IMPRESORA', '')
ETIQUETA_ANCHO   = 80
ETIQUETA_ALTO    = 100

# Xprinter DPI nativo = 203dpi.
# 80mm a 203dpi = 638px, 100mm a 203dpi = 799px
# Usar el DPI nativo evita que CUPS genere 2 etiquetas.
PRINTER_DPI = 203
OUT_W = int(ETIQUETA_ANCHO / 25.4 * PRINTER_DPI)  # 638
OUT_H = int(ETIQUETA_ALTO  / 25.4 * PRINTER_DPI)  # 799
PAD   = 47  # proporcional (70/945 * 638)

CONFIGS = {
    'mercadolibre': {'page': 0, 'cx': 0,  'cy': 0, 'cw': 36,  'ch': 79},
    'mlmelinet':    {'page': 0, 'cx': 0,  'cy': 0, 'cw': 35,  'ch': 78},
    'gestionpost':  {'page': 0, 'cx': 0,  'cy': 0, 'cw': 48,  'ch': 51},
    'shopify':      {'page': 0, 'cx': 0,  'cy': 0, 'cw': 100, 'ch': 100},
}

PALABRAS_CLAVE = {
    'gestionpost':  ['gestionpost', 'entregamos felicidad', 'ursec:', 'gestionpost.com.uy'],
    'shopify':      ['facturar a', 'pedido #', 'packing slip', 'artículos'],
    'mlmelinet':    ['melinet', 'ues sa', 'ues111', 'xmv01', 'uesm'],
    'mercadolibre': ['mercado libre', 'envio:', 'venta:', 'zona ', 'flex'],
}


# ── FUENTES ────────────────────────────────────────────────────────────────────
def fuente(tamano, negrita=False):
    """Carga la mejor fuente disponible en la Raspberry Pi."""
    sufijo = 'Bold' if negrita else 'Regular'
    rutas = [
        f'/usr/share/fonts/truetype/dejavu/DejaVuSans-{"Bold" if negrita else ""}.ttf',
        f'/usr/share/fonts/truetype/liberation/LiberationSans-{sufijo}.ttf',
        f'/usr/share/fonts/truetype/freefont/FreeSans{"Bold" if negrita else ""}.ttf',
        f'/usr/share/fonts/truetype/noto/NotoSans-{sufijo}.ttf',
    ]
    for ruta in rutas:
        try:
            return ImageFont.truetype(ruta, tamano)
        except:
            continue
    return ImageFont.load_default()

def ancho(draw, texto, f):
    try:
        return int(draw.textlength(texto, font=f))
    except:
        return draw.textbbox((0,0), texto, font=f)[2]

def envolver(draw, texto, f, max_w):
    """Corta una línea larga en varias líneas."""
    palabras = texto.split()
    lineas, actual = [], ''
    for p in palabras:
        prueba = actual + ' ' + p if actual else p
        if ancho(draw, prueba, f) <= max_w:
            actual = prueba
        else:
            if actual: lineas.append(actual)
            actual = p
    if actual: lineas.append(actual)
    return lineas or [texto]


# ── GENERAR ETIQUETA DESDE TEXTO ───────────────────────────────────────────────
def generar_etiqueta_texto(nombre, direccion='', ciudad='', pais='Uruguay',
                            telefono='', notas='', pedido=''):
    """
    Genera una imagen PNG de etiqueta 80×100mm desde datos de texto.
    Misma apariencia que la de Shopify: KAI DECO arriba, datos abajo.
    """
    img  = Image.new('RGB', (OUT_W, OUT_H), 'white')
    draw = ImageDraw.Draw(img)

    # Borde fino
    draw.rectangle([8, 8, OUT_W-8, OUT_H-8], outline='#dddddd', width=3)

    HEADER_H = 210
    y = 0

    # ── Header negro ──
    draw.rectangle([0, 0, OUT_W, HEADER_H], fill='black')
    f_hdr = fuente(125, negrita=True)
    txt   = 'KAI DECO'
    tw    = ancho(draw, txt, f_hdr)
    draw.text(((OUT_W - tw)//2, (HEADER_H - 125)//2), txt, fill='white', font=f_hdr)
    y = HEADER_H + 45

    # ── Número de pedido ──
    if pedido:
        draw.text((PAD, y), f'Pedido #{pedido}', fill='#aaaaaa', font=fuente(42))
        y += 58

    # ── "ENVIAR A" ──
    draw.text((PAD, y), 'ENVIAR A', fill='#aaaaaa', font=fuente(44, negrita=True))
    y += 60
    draw.line([(PAD, y), (OUT_W-PAD, y)], fill='#e0e0e0', width=2)
    y += 28

    # ── Nombre ──
    f_nom = fuente(86, negrita=True)
    # Reducir si es muy largo
    sz = 86
    while ancho(draw, nombre, f_nom) > OUT_W - PAD*2 and sz > 52:
        sz -= 4
        f_nom = fuente(sz, negrita=True)
    draw.text((PAD, y), nombre, fill='black', font=f_nom)
    y += sz + 18

    # ── Dirección ──
    f_dir  = fuente(62)
    linea_h = 76
    max_w   = OUT_W - PAD*2
    lineas  = []
    if direccion: lineas += envolver(draw, direccion, f_dir, max_w)
    if ciudad:    lineas += envolver(draw, ciudad,    f_dir, max_w)
    if pais:      lineas += envolver(draw, pais,      f_dir, max_w)

    for linea in lineas:
        draw.text((PAD, y), linea, fill='#222222', font=f_dir)
        y += linea_h

    # ── Notas ──
    if notas and notas.strip():
        y += 10
        draw.line([(PAD, y), (OUT_W-PAD, y)], fill='#f0f0f0', width=2)
        y += 20
        draw.text((PAD, y), 'Nota:', fill='#666666', font=fuente(48))
        y += 60
        f_nota = fuente(54)
        for linea in envolver(draw, notas, f_nota, max_w):
            draw.text((PAD, y), linea, fill='#444444', font=f_nota)
            y += 68

    # ── Teléfono (abajo fijo) ──
    if telefono and telefono.strip():
        phone_y = OUT_H - 155
        draw.line([(PAD, phone_y-28), (OUT_W-PAD, phone_y-28)], fill='black', width=4)
        draw.text((PAD, phone_y), f'Tel: {telefono}', fill='black', font=fuente(76, negrita=True))

    return img


# ── UTILIDADES ─────────────────────────────────────────────────────────────────
def verificar_clave(req):
    clave = req.headers.get('X-API-Key') or req.form.get('api_key', '')
    return hmac.compare_digest(clave, API_KEY)

def detectar_tipo(nombre_archivo, pdf_bytes=None):
    if pdf_bytes and PYPDF_OK:
        try:
            texto = PdfReader(io.BytesIO(pdf_bytes)).pages[0].extract_text().lower()
            for tipo, palabras in PALABRAS_CLAVE.items():
                if any(p in texto for p in palabras):
                    print(f'  Detectado por contenido: {tipo}')
                    return tipo
        except Exception as e:
            print(f'  Advertencia PDF: {e}')
    nombre = (nombre_archivo or '').lower()
    if 'packing_slip' in nombre or 'shopify' in nombre: return 'shopify'
    if 'gestion' in nombre: return 'gestionpost'
    return 'mercadolibre'

def es_telefono_uy(l):
    c = re.sub(r'[\s\-(). ]', '', l)
    return bool(
        re.match(r'^(\+?598)?0?9\d{7,8}$', c) or
        re.match(r'^(\+?598)?2\d{7}$', c)     or
        re.match(r'^(\+?598)?[34]\d{7}$', c)
    )

def pdf_a_imagen(pdf_bytes, tipo):
    cfg = CONFIGS.get(tipo, CONFIGS['mercadolibre'])
    imgs = convert_from_bytes(pdf_bytes, dpi=300,
                               first_page=cfg['page']+1, last_page=cfg['page']+1)
    img = imgs[0]
    w, h = img.size
    sx, sy = int(cfg['cx']/100*w), int(cfg['cy']/100*h)
    sw, sh = int(cfg['cw']/100*w), int(cfg['ch']/100*h)
    return img.crop((sx, sy, sx+sw, sy+sh)).resize((OUT_W, OUT_H), Image.LANCZOS)

def imprimir_imagen(img_pil):
    # Rotar 180° — corrige la orientación invertida de la Xprinter
    img_pil = img_pil.rotate(180)

    with tempfile.NamedTemporaryFile(suffix='.png', delete=False) as f:
        img_pil.save(f, format='PNG', dpi=(300, 300))
        tmp = f.name
    try:
        cmd = [
            'lp',
            '-o', f'media=Custom.{ETIQUETA_ANCHO}x{ETIQUETA_ALTO}mm',
            '-o', 'orientation-requested=3',      # portrait
            '-o', f'printer-resolution={PRINTER_DPI}dpi',  # DPI nativo Xprinter
            '-o', 'scaling=100',                  # sin escalar
        ]
        if NOMBRE_IMPRESORA: cmd += ['-d', NOMBRE_IMPRESORA]
        cmd.append(tmp)
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return r.returncode == 0, r.stdout.strip() or r.stderr.strip()
    except Exception as e:
        return False, str(e)
    finally:
        os.unlink(tmp)


# ══════════════════════════════════════════════════════════════════════════════
# ENDPOINTS
# ══════════════════════════════════════════════════════════════════════════════

@app.route('/convertir-e-imprimir', methods=['POST'])
def convertir_e_imprimir():
    """Recibe PDF, detecta tipo, convierte e imprime."""
    if not verificar_clave(request): return jsonify({'error': 'Clave incorrecta'}), 401
    if 'pdf' not in request.files:   return jsonify({'error': 'Falta el PDF'}), 400
    archivo   = request.files['pdf']
    pdf_bytes = archivo.read()
    tipo = request.form.get('tipo', '').strip().lower()
    if tipo not in CONFIGS:
        tipo = detectar_tipo(archivo.filename, pdf_bytes)
    print(f'  PDF: {archivo.filename} → tipo={tipo}')
    try:
        img = pdf_a_imagen(pdf_bytes, tipo)
        exito, detalle = imprimir_imagen(img)
        if exito:
            return jsonify({'ok': True, 'tipo': tipo, 'mensaje': f'Imprimiendo ({tipo})'})
        return jsonify({'ok': False, 'error': detalle}), 500
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/etiqueta-manual', methods=['POST'])
def etiqueta_manual():
    """
    Genera e imprime una etiqueta desde datos de texto.
    Ideal para el flujo manual de WhatsApp en Otimify.

    Parámetros (form-data o JSON):
      api_key   → clave de seguridad
      nombre    → nombre del cliente  (OBLIGATORIO)
      direccion → dirección
      ciudad    → ciudad / código postal
      pais      → país (default: Uruguay)
      telefono  → teléfono
      notas     → notas adicionales (opcional)
      pedido    → número de pedido (opcional)
      imprimir  → 'si' para imprimir, 'no' para solo devolver la imagen (default: si)
    """
    if not verificar_clave(request): return jsonify({'error': 'Clave incorrecta'}), 401

    # Aceptar tanto form-data como JSON
    data = request.form if request.form else (request.json or {})
    nombre = (data.get('nombre') or data.get('name') or '').strip()
    if not nombre:
        return jsonify({'error': 'El campo "nombre" es obligatorio'}), 400

    direccion = (data.get('direccion') or data.get('address') or '').strip()
    ciudad    = (data.get('ciudad')    or data.get('city')    or '').strip()
    pais      = (data.get('pais')      or data.get('country') or 'Uruguay').strip()
    telefono  = (data.get('telefono')  or data.get('phone')   or '').strip()
    notas     = (data.get('notas')     or data.get('notes')   or '').strip()
    pedido    = (data.get('pedido')    or data.get('order')   or '').strip()
    solo_img  = (data.get('imprimir')  or 'si').strip().lower() == 'no'

    print(f'  Etiqueta manual: {nombre} | {telefono}')

    try:
        img = generar_etiqueta_texto(
            nombre=nombre, direccion=direccion, ciudad=ciudad,
            pais=pais, telefono=telefono, notas=notas, pedido=pedido
        )

        if solo_img:
            # Solo devolver la imagen (para previsualizar)
            buf = io.BytesIO()
            img.save(buf, format='PNG', dpi=(300, 300))
            buf.seek(0)
            return send_file(buf, mimetype='image/png',
                             as_attachment=True, download_name='etiqueta_manual.png')

        # Imprimir directamente
        exito, detalle = imprimir_imagen(img)
        if exito:
            print(f'  ✓ Imprimiendo etiqueta de {nombre}')
            return jsonify({
                'ok':     True,
                'nombre': nombre,
                'mensaje': f'✅ Imprimiendo etiqueta de {nombre}'
            })
        return jsonify({'ok': False, 'error': detalle}), 500

    except Exception as e:
        print(f'  ✗ Error: {e}')
        return jsonify({'error': str(e)}), 500


@app.route('/convertir', methods=['POST'])
def solo_convertir():
    """Solo devuelve la imagen PNG del PDF, sin imprimir."""
    if not verificar_clave(request): return jsonify({'error': 'Clave incorrecta'}), 401
    if 'pdf' not in request.files:   return jsonify({'error': 'Falta el PDF'}), 400
    archivo   = request.files['pdf']
    pdf_bytes = archivo.read()
    tipo = request.form.get('tipo', '').strip().lower()
    if tipo not in CONFIGS:
        tipo = detectar_tipo(archivo.filename, pdf_bytes)
    try:
        img = pdf_a_imagen(pdf_bytes, tipo)
        buf = io.BytesIO()
        img.save(buf, format='PNG', dpi=(300, 300))
        buf.seek(0)
        return send_file(buf, mimetype='image/png',
                         as_attachment=True, download_name=f'etiqueta_{tipo}.png')
    except Exception as e:
        return jsonify({'error': str(e)}), 500


@app.route('/estado', methods=['GET'])
def estado():
    try:
        imp = subprocess.run(['lpstat', '-p'], capture_output=True, text=True, timeout=5)
        lista = imp.stdout.strip() or 'ninguna detectada'
    except:
        lista = 'no disponible'
    return jsonify({
        'ok':      True,
        'servidor': 'Convertidor Etiquetas - Kai Deco',
        'endpoints': {
            'PDF':    'POST /convertir-e-imprimir  (campo: pdf)',
            'Manual': 'POST /etiqueta-manual       (campos: nombre, direccion, ciudad, pais, telefono, notas)',
        },
        'impresoras': lista,
    })


if __name__ == '__main__':
    puerto = int(os.environ.get('PUERTO', 3333))
    print(f'\n{"="*55}')
    print(f' CONVERTIDOR DE ETIQUETAS - KAI DECO')
    print(f' Puerto  : {puerto}')
    print(f' PDF     : POST /convertir-e-imprimir')
    print(f' Manual  : POST /etiqueta-manual')
    print(f' Estado  : GET  /estado')
    print(f'{"="*55}\n')
    app.run(host='0.0.0.0', port=puerto, debug=False)
