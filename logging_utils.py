import base64
import hashlib
import json
import time
from config import MAX_LOG_BINARY_PREVIEW, MAX_LOG_TEXT_BODY


def build_request_body_log(body: bytes, content_type: str) -> dict:
    content_type = (content_type or "").lower()

    if (
        "application/json" in content_type
        or "text/plain" in content_type
        or "text/html" in content_type
        or "application/x-www-form-urlencoded" in content_type
    ):
        try:
            text = body.decode("utf-8", errors="replace")
        except Exception:
            text = repr(body)

        if len(text) > MAX_LOG_TEXT_BODY:
            return {
                "kind": "text",
                "truncated": True,
                "length": len(text),
                "body": text[:MAX_LOG_TEXT_BODY],
            }

        return {
            "kind": "text",
            "truncated": False,
            "length": len(text),
            "body": text,
        }

    preview = body[:MAX_LOG_BINARY_PREVIEW]
    return {
        "kind": "binary",
        "length": len(body),
        "sha256": hashlib.sha256(body).hexdigest(),
        "preview_hex": preview.hex(),
        "preview_base64": base64.b64encode(preview).decode("ascii"),
        "truncated_preview": len(body) > len(preview),
    }


def log_request_response(handler, start_time, status_code, response_text, request_body_log=None, extra=None):
    duration_ms = round((time.time() - start_time) * 1000, 2)
    log_entry = {
        "client_ip": handler.client_address[0],
        "method": handler.command,
        "path": handler.path,
        "status_code": status_code,
        "duration_ms": duration_ms,
        "content_type": handler.headers.get("Content-Type", ""),
        "content_length": handler.headers.get("Content-Length", ""),
        "request_body": request_body_log,
        "response": response_text,
    }

    if extra:
        log_entry["extra"] = extra

    print(json.dumps(log_entry, ensure_ascii=False), flush=True)
