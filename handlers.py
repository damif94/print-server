import json
import os
import secrets
import shutil
import subprocess
import tempfile
import time
from http.server import BaseHTTPRequestHandler
from urllib.parse import urlparse

from PIL import Image

from config import API_KEY, INDEX_FILE, LABEL_HEIGHT_PX, LABEL_MEDIA, LABEL_WIDTH_PX, PRINTER_DPI, PRINTER_NAME
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
            self,
            self.start_time,
            status_code,
            body.decode("utf-8", errors="replace"),
            request_body_log=request_body_log,
            extra=extra,
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
            self,
            self.start_time,
            200,
            f"served_file:{os.path.basename(path)}",
            extra={"served_file": path},
        )

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

    def do_GET(self):
        self.start_time = time.time()
        parsed = urlparse(self.path)

        if parsed.path in ["/", "/index.html"]:
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

    def do_POST(self):
        self.start_time = time.time()
        parsed = urlparse(self.path)

        if parsed.path != "/print":
            self._send_json(404, {"ok": False, "error": "not_found"})
            return

        if not self._is_authorized():
            self._send_json(401, {"ok": False, "error": "unauthorized"})
            return

        content_type = self.headers.get("Content-Type", "").lower()

        allowed_types = {
            "application/pdf": ".pdf",
            "image/jpeg": ".jpg",
            "image/png": ".png",
        }

        matched_type = None
        matched_ext = None
        for mime_type, ext in allowed_types.items():
            if mime_type in content_type:
                matched_type = mime_type
                matched_ext = ext
                break

        if not matched_type:
            self._send_json(
                400,
                {
                    "ok": False,
                    "error": "invalid_content_type",
                    "expected": list(allowed_types.keys()),
                },
            )
            return

        content_length = self.headers.get("Content-Length")
        if not content_length:
            self._send_json(411, {"ok": False, "error": "missing_content_length"})
            return

        try:
            length = int(content_length)
        except ValueError:
            self._send_json(400, {"ok": False, "error": "invalid_content_length"})
            return

        if length <= 0:
            self._send_json(400, {"ok": False, "error": "empty_body"})
            return

        temp_dir = tempfile.mkdtemp(prefix="printapi_")
        upload_path = os.path.join(temp_dir, f"job{matched_ext}")
        raw_body = b""

        try:
            chunks = []
            remaining = length
            while remaining > 0:
                chunk = self.rfile.read(min(65536, remaining))
                if not chunk:
                    break
                chunks.append(chunk)
                remaining -= len(chunk)

            raw_body = b"".join(chunks)
            request_body_log = build_request_body_log(raw_body, content_type)

            with open(upload_path, "wb") as f:
                f.write(raw_body)

            if os.path.getsize(upload_path) == 0:
                self._send_json(
                    400,
                    {"ok": False, "error": "empty_file"},
                    request_body_log=request_body_log,
                )
                return

            print_path = upload_path
            if matched_type in ("image/png", "image/jpeg"):
                resized_path = os.path.join(temp_dir, f"resized{matched_ext}")
                self._resize_image_for_label(upload_path, resized_path)
                print_path = resized_path

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
                    {
                        "ok": False,
                        "error": "print_failed",
                        "stdout": result.stdout.strip(),
                        "stderr": result.stderr.strip(),
                    },
                    request_body_log=request_body_log,
                    extra={
                        "lp_command": cmd,
                        "lp_returncode": result.returncode,
                        "detected_content_type": matched_type,
                    },
                )
                return

            self._send_json(
                200,
                {
                    "ok": True,
                    "message": "print_submitted",
                    "printer": PRINTER_NAME,
                    "detected_content_type": matched_type,
                    "lp_output": result.stdout.strip(),
                },
                request_body_log=request_body_log,
                extra={
                    "lp_command": cmd,
                    "lp_returncode": result.returncode,
                    "detected_content_type": matched_type,
                },
            )

        except Exception as e:
            request_body_log = build_request_body_log(raw_body, content_type) if raw_body else None
            self._send_json(
                500,
                {"ok": False, "error": "server_error", "detail": str(e)},
                request_body_log=request_body_log,
            )
        finally:
            shutil.rmtree(temp_dir, ignore_errors=True)
