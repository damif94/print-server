import io
import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse, parse_qs

from PIL import Image

from config import API_KEY, INDEX_FILE, LABEL_HEIGHT_PX, LABEL_MEDIA, LABEL_WIDTH_PX, PRINTER_DPI, PRINTER_NAME
from label_processor import detect_type, generate_text_label, pdf_to_label_image
from logging_utils import build_request_body_log, log_request_response


class PrintHandler(BaseHTTPRequestHandler):
    def log_message(self, format, *args):
        return

    def _json_bytes(self, payload: dict) -> bytes:
        return json.dumps(payload, ensure_ascii=False).encode("utf-8")

    def _send_json(self, status_code: int, payload: dict, request_body_log=None, extra=None):
        body = self._json_bytes(payload)
        self.send_response(status_code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        log_request_response(
            self, self.start_time, status_code,
            body.decode("utf-8", errors="replace"),
            request_body_log=request_body_log, extra=extra,
        )

    def _send_file(self, path: str):
        with open(path, "rb") as f:
            body = f.read()
        self.send_response(200)
        self.send_header("Content-Type", "text/html; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)
        log_request_response(
            self, self.start_time, 200,
            f"served_file:{os.path.basename(path)}",
            extra={"served_file": path},
        )

    def _send_image(self, img: Image.Image, extra_headers: dict | None = None):
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        body = buf.getvalue()
        self.send_response(200)
        self.send_header("Content-Type", "image/png")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)
        log_request_response(
            self, self.start_time, 200,
            f"image/png:{len(body)}bytes",
            extra=extra_headers,
        )

    def _read_body(self) -> tuple:
        """Read full request body. Returns (bytes | None, error_sent: bool)."""
        cl = self.headers.get("Content-Length")
        if not cl:
            self._send_json(411, {"ok": False, "error": "missing_content_length"})
            return None, True
        try:
            length = int(cl)
        except ValueError:
            self._send_json(400, {"ok": False, "error": "invalid_content_length"})
            return None, True
        if length <= 0:
            self._send_json(400, {"ok": False, "error": "empty_body"})
            return None, True
        chunks, remaining = [], length
        while remaining > 0:
            chunk = self.rfile.read(min(65536, remaining))
            if not chunk:
                break
            chunks.append(chunk)
            remaining -= len(chunk)
        return b"".join(chunks), False

    def _resize_image_for_label(self, input_path: str, output_path: str):
        with Image.open(input_path) as img:
            img = img.rotate(180, expand=True)
            img.thumbnail((LABEL_WIDTH_PX, LABEL_HEIGHT_PX), Image.LANCZOS)
            img.save(output_path)

    def _is_authorized(self):
        provided_key = self.headers.get("X-API-Key", "")
        if not provided_key:
            return False
        return secrets.compare_digest(provided_key, API_KEY)

    # ── GET ───────────────────────────────────────────────────────────────────

    def do_GET(self):
        self.start_time = time.time()
        parsed = urlparse(self.path)

        if parsed.path in ("/", "/index.html"):
            if not os.path.exists(INDEX_FILE):
                self._send_json(500, {"ok": False, "error": "missing_index_html"})
                return
            self._send_file(INDEX_FILE)
            return

        if parsed.path == "/health":
            if not self._is_authorized():
                self._send_json(401, {"ok": False, "error": "unauthorized"})
                return
            self._send_json(200, {"ok": True, "printer": PRINTER_NAME})
            return

        self._send_json(404, {"ok": False, "error": "not_found"})

    # ── POST ──────────────────────────────────────────────────────────────────

    def do_POST(self):
        self.start_time = time.time()
        parsed = urlparse(self.path)
        params = parse_qs(parsed.query)

        if not self._is_authorized():
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return

        route = parsed.path

        if route == "/detect":
            self._post_detect(params)
        elif route == "/convert":
            self._post_convert(params)
        elif route == "/label":
            self._post_label(params)
        elif route == "/print":
            self._post_print(params)
        else:
            self._send_json(404, {"ok": False, "error": "not_found"})

    # ── POST /detect ──────────────────────────────────────────────────────────

    def _post_detect(self, params):
        content_type = self.headers.get("Content-Type", "").lower()
        if "application/pdf" not in content_type:
            self._send_json(400, {"ok": False, "error": "pdf_required"})
            return
        body, err = self._read_body()
        if err:
            return
        try:
            filename   = self.headers.get("X-Filename", "")
            label_type = detect_type(body, filename)
            self._send_json(200, {"ok": True, "type": label_type})
        except Exception as e:
            self._send_json(500, {"ok": False, "error": "detection_failed", "detail": str(e)})

    # ── POST /convert ─────────────────────────────────────────────────────────

    def _post_convert(self, params):
        content_type = self.headers.get("Content-Type", "").lower()
        if "application/pdf" not in content_type:
            self._send_json(400, {"ok": False, "error": "pdf_required"})
            return
        body, err = self._read_body()
        if err:
            return
        try:
            filename   = self.headers.get("X-Filename", "")
            label_type = (params.get("type", [None])[0]
                          or self.headers.get("X-Label-Type")
                          or detect_type(body, filename))
            img = pdf_to_label_image(body, label_type)
            self._send_image(img, {"X-Label-Type": label_type})
        except Exception as e:
            self._send_json(500, {"ok": False, "error": "conversion_failed", "detail": str(e)})

    # ── POST /label ───────────────────────────────────────────────────────────

    def _post_label(self, params):
        content_type = self.headers.get("Content-Type", "").lower()
        if "application/json" not in content_type:
            self._send_json(400, {"ok": False, "error": "json_required"})
            return
        body, err = self._read_body()
        if err:
            return
        try:
            data = json.loads(body)
        except json.JSONDecodeError as e:
            self._send_json(400, {"ok": False, "error": "invalid_json", "detail": str(e)})
            return
        if not data.get("name", "").strip():
            self._send_json(400, {"ok": False, "error": "name_required"})
            return
        try:
            img = generate_text_label(
                name=data.get("name", ""),
                address=data.get("address", ""),
                city=data.get("city", ""),
                country=data.get("country", "Uruguay"),
                phone=data.get("phone", ""),
                notes=data.get("notes", ""),
                order=data.get("order", ""),
            )
            self._send_image(img)
        except Exception as e:
            self._send_json(500, {"ok": False, "error": "generation_failed", "detail": str(e)})

    # ── POST /print ───────────────────────────────────────────────────────────

    def _post_print(self, params):
        content_type = self.headers.get("Content-Type", "").lower()

        # ── JSON con URL para Otimify ──────────────────────────────────────────
        if "application/json" in content_type:
            body, err = self._read_body()
            if err:
                return
            try:
                import json as _json
                data = _json.loads(body)
            except Exception as e:
                self._send_json(400, {"ok": False, "error": "invalid_json", "detail": str(e)})
                return
            raw_url = data.get("url", "")
            if isinstance(raw_url, list):
                raw_url = raw_url[0] if raw_url else ""
            url = str(raw_url).strip()
            # Si llega como string con múltiples URLs separadas por coma, tomar la primera
            if "," in url:
                url = url.split(",")[0].strip()
            if not url:
                self._send_json(400, {"ok": False, "error": "url_required"})
                return
            try:
                import urllib.request as _ur
                req = _ur.Request(url, headers={"User-Agent": "PrintServer/1.0"})
                with _ur.urlopen(req, timeout=30) as resp:
                    pdf_bytes = resp.read()
            except Exception as e:
                self._send_json(500, {"ok": False, "error": "download_failed", "detail": str(e)})
                return
            filename = url.split("/")[-1].split("?")[0]
            label_type = detect_type(pdf_bytes, filename)
            import tempfile, shutil, subprocess, os
            temp_dir = tempfile.mkdtemp(prefix="printapi_")
            try:
                img = pdf_to_label_image(pdf_bytes, label_type)
                img = img.rotate(180, expand=True)
                print_path = os.path.join(temp_dir, "label.png")
                img.save(print_path)
                cmd = ["lp", "-d", PRINTER_NAME, "-o", f"media={LABEL_MEDIA}",
                       "-o", "orientation-requested=3",
                       "-o", f"printer-resolution={PRINTER_DPI}dpi",
                       "-o", "scaling=100", print_path]
                result = subprocess.run(cmd, capture_output=True, text=True, check=False)
                if result.returncode != 0:
                    self._send_json(500, {"ok": False, "error": "print_failed",
                                          "stdout": result.stdout.strip(), "stderr": result.stderr.strip()})
                    return
                self._send_json(200, {"ok": True, "message": "print_submitted",
                                      "source": "url", "detected_label_type": label_type,
                                      "lp_output": result.stdout.strip()})
            except Exception as e:
                self._send_json(500, {"ok": False, "error": "server_error", "detail": str(e)})
            finally:
                shutil.rmtree(temp_dir, ignore_errors=True)
            return
        # ── FIN bloque JSON/URL ────────────────────────────────────────────────

        content_type = self.headers.get("Content-Type", "").lower()

        allowed_types = {
            "application/pdf": ".pdf",
            "image/jpeg":      ".jpg",
            "image/png":       ".png",
        }
        matched_type = matched_ext = None
        for mime, ext in allowed_types.items():
            if mime in content_type:
                matched_type, matched_ext = mime, ext
                break

        if not matched_type:
            self._send_json(400, {"ok": False, "error": "invalid_content_type",
                                  "expected": list(allowed_types.keys())})
            return

        body, err = self._read_body()
        if err:
            return

        request_body_log = build_request_body_log(body, content_type)

        if not body:
            self._send_json(400, {"ok": False, "error": "empty_file"},
                            request_body_log=request_body_log)
            return

        temp_dir = tempfile.mkdtemp(prefix="printapi_")
        try:
            if matched_type == "application/pdf":
                filename   = self.headers.get("X-Filename", "")
                label_type = (params.get("type", [None])[0]
                              or self.headers.get("X-Label-Type")
                              or detect_type(body, filename))
                img        = pdf_to_label_image(body, label_type)
                img        = img.rotate(180, expand=True)
                print_path = os.path.join(temp_dir, "label.png")
                img.save(print_path)
                extra_info = {"detected_label_type": label_type}
            else:
                upload_path = os.path.join(temp_dir, f"job{matched_ext}")
                with open(upload_path, "wb") as f:
                    f.write(body)
                print_path = os.path.join(temp_dir, f"resized{matched_ext}")
                self._resize_image_for_label(upload_path, print_path)
                extra_info = {}

            cmd = [
                "lp",
                "-d", PRINTER_NAME,
                "-o", f"media={LABEL_MEDIA}",
                "-o", "orientation-requested=3",
                "-o", f"printer-resolution={PRINTER_DPI}dpi",
                "-o", "scaling=100",
                print_path,
            ]
            result = subprocess.run(cmd, capture_output=True, text=True, check=False)

            if result.returncode != 0:
                self._send_json(
                    500,
                    {"ok": False, "error": "print_failed",
                     "stdout": result.stdout.strip(), "stderr": result.stderr.strip()},
                    request_body_log=request_body_log,
                    extra={"lp_command": cmd, "lp_returncode": result.returncode,
                           "content_type": matched_type, **extra_info},
                )
                return

            self._send_json(
                200,
                {"ok": True, "message": "print_submitted", "printer": PRINTER_NAME,
                 "content_type": matched_type, "lp_output": result.stdout.strip(), **extra_info},
                request_body_log=request_body_log,
                extra={"lp_command": cmd, "lp_returncode": result.returncode,
                       "content_type": matched_type, **extra_info},
            )

        except Exception as e:
            self._send_json(
                500, {"ok": False, "error": "server_error", "detail": str(e)},
                request_body_log=request_body_log,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
