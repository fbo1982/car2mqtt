"""Opt-in MySilence HTTP trace. Writes masked pre-parse bytes to a private rotating file."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import threading
import time
from urllib.parse import urlsplit, parse_qsl, urlencode, urlunsplit
from datetime import datetime, timezone

import requests

TRACE_DIR = Path(os.environ.get("APP_DATA_DIR", "/config/car2mqtt")) / "silence-http-traces"
MAX_BYTES = 2 * 1024 * 1024
MAX_RESPONSE_BYTES = 256 * 1024
_LOCK = threading.RLock()
SECRET_KEY = re.compile(r"password|token|secret|authorization|cookie|apikey|api_key|session|credential|refresh|email|account|imei|frameno|frame_no|vin|gps|latitude|longitude|location|coordinates|phone|address|deviceid|serial", re.I)
QUERY_SECRET = re.compile(r"key|password|token|secret|auth|email|session|code", re.I)
# Extra fallback for JSON response/request text when a response is not valid JSON.
TEXT_SECRETS = re.compile(r'(?i)(["\\]?[^"\\]{0,60}(?:password|token|secret|authorization|cookie|apikey|api_key|imei|vin|email|latitude|longitude|frameno)[^"\\]{0,30}["\\]?\s*:\s*)("(?:\\.|[^"\\])*"|[^,}\s]+)')


def _mask(value, key=""):
    if SECRET_KEY.search(str(key)):
        return "[REDACTED]"
    if isinstance(value, dict):
        return {k: _mask(v, k) for k, v in value.items()}
    if isinstance(value, list):
        return [_mask(v) for v in value]
    return value


def _safe_body(data: bytes) -> str:
    text = data.decode("utf-8", errors="replace")
    try:
        obj = json.loads(text)
    except (ValueError, TypeError):
        # Non-JSON responses are deliberately not logged verbatim: arbitrary
        # HTML/text can contain tokens and cannot be safely filtered.
        return f"[NON-JSON BODY OMITTED; sha256={hashlib.sha256(data).hexdigest()}]"
    return json.dumps(_mask(obj), ensure_ascii=False, indent=2)


def _safe_url(url: str) -> str:
    parsed = urlsplit(url)
    query = urlencode([(k, "[REDACTED]" if QUERY_SECRET.search(k) else v)
                       for k, v in parse_qsl(parsed.query, keep_blank_values=True)])
    return urlunsplit((parsed.scheme, parsed.netloc, parsed.path, query, ""))


def _headers(headers) -> dict:
    return {str(k): "[REDACTED]" if SECRET_KEY.search(str(k)) else str(v)
            for k, v in (headers or {}).items()}


def _write(vehicle_id: str, message: str):
    # Only an internal identifier is used, never a user-controlled path.
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", str(vehicle_id))[:100]
    with _LOCK:
        TRACE_DIR.mkdir(mode=0o700, parents=True, exist_ok=True)
        try:
            os.chmod(TRACE_DIR, 0o700)
        except OSError:
            pass
        path = TRACE_DIR / (safe_id + ".log")
        if path.exists() and path.stat().st_size + len(message.encode("utf-8")) > MAX_BYTES:
            old = path.with_suffix(".log.1")
            path.replace(old)
        fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_APPEND, 0o600)
        try:
            os.fchmod(fd, 0o600)
            with os.fdopen(fd, "a", encoding="utf-8") as file:
                file.write(message + "\n")
        except BaseException:
            raise


def read_trace(vehicle_id: str) -> str | None:
    """Return the log text, or None when no current log file exists."""
    safe_id = re.sub(r"[^a-zA-Z0-9_-]", "_", str(vehicle_id))[:100]
    path = TRACE_DIR / (safe_id + ".log")
    with _LOCK:
        try:
            return path.read_text(encoding="utf-8", errors="replace")
        except FileNotFoundError:
            return None


class SilenceHttpTrace:
    def __init__(self, vehicle_id: str):
        self.vehicle_id = vehicle_id

    def request(self, method: str, url: str, **kwargs):
        stamp = datetime.now(timezone.utc).isoformat()
        req_id = hashlib.sha256(f"{stamp}:{self.vehicle_id}".encode()).hexdigest()[:12]
        request_body = kwargs.get("json") or kwargs.get("data")
        if isinstance(request_body, (dict, list)):
            body_text = json.dumps(_mask(request_body), ensure_ascii=False)
        elif request_body is None:
            body_text = "[NONE]"
        else:
            body_text = "[UNSTRUCTURED BODY OMITTED]"
        _write(self.vehicle_id, f"[{stamp}] REQUEST {req_id} {method} {_safe_url(url)}\n"
              f"Headers: {json.dumps(_headers(kwargs.get('headers')), ensure_ascii=False)}\nBody: {body_text}")
        started = time.monotonic()
        try:
            response = requests.request(method, url, **kwargs)
        except requests.RequestException as exc:
            _write(self.vehicle_id, f"[{datetime.now(timezone.utc).isoformat()}] ERROR {req_id} "
                   f"{type(exc).__name__}; after={time.monotonic()-started:.3f}s; "
                   "no complete HTTP response available")
            raise
        content = response.content  # capture raw decoded HTTP entity bytes before res.json()
        truncated = len(content) > MAX_RESPONSE_BYTES
        snippet = content[:MAX_RESPONSE_BYTES]
        _write(self.vehicle_id, f"[{datetime.now(timezone.utc).isoformat()}] RESPONSE {req_id} "
               f"HTTP {response.status_code}; after={time.monotonic()-started:.3f}s; "
               f"bytes={len(content)}; sha256={hashlib.sha256(content).hexdigest()}\n"
               f"Headers: {json.dumps(_headers(response.headers), ensure_ascii=False)}\n"
               f"Body (masked before JSON parsing): {_safe_body(snippet)}"
               + ("\n[TRUNCATED at 256 KiB]" if truncated else ""))
        return response
