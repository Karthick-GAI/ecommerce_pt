"""
Structured JSON logging middleware.

Emits one log line per request containing:
  - trace_id  (UUID per request — used to correlate logs across services)
  - service   (injected at setup time)
  - method, path, status_code, duration_ms
  - user_id   (extracted from JWT if present, for security audit)

Usage:
    from nfr.structured_logging import setup_logging, RequestLoggingMiddleware

    setup_logging(service_name="user_management")
    app.add_middleware(RequestLoggingMiddleware, service_name="user_management")
"""

import json
import logging
import time
import uuid
from typing import Callable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import Response


# ── JSON log formatter ────────────────────────────────────────────────────────

class JsonFormatter(logging.Formatter):
    """Emit every log record as a single-line JSON object."""

    def format(self, record: logging.LogRecord) -> str:
        log = {
            "ts":      self.formatTime(record, "%Y-%m-%dT%H:%M:%S"),
            "level":   record.levelname,
            "service": getattr(record, "service", "unknown"),
            "logger":  record.name,
            "msg":     record.getMessage(),
        }
        # Merge any extra fields passed via extra={...}
        for key, value in record.__dict__.items():
            if key not in logging.LogRecord.__dict__ and key not in log and not key.startswith("_"):
                log[key] = value
        if record.exc_info:
            log["exc"] = self.formatException(record.exc_info)
        return json.dumps(log, default=str)


def setup_logging(service_name: str, level: int = logging.INFO) -> logging.Logger:
    """
    Configure the root logger to emit structured JSON.
    Call once at application startup before the app object is created.
    """
    handler = logging.StreamHandler()
    handler.setFormatter(JsonFormatter())

    root = logging.getLogger()
    root.handlers.clear()
    root.addHandler(handler)
    root.setLevel(level)

    logger = logging.getLogger(service_name)
    logger.info("Structured logging initialised", extra={"service": service_name})
    return logger


# ── Request / response middleware ─────────────────────────────────────────────

class RequestLoggingMiddleware(BaseHTTPMiddleware):
    """
    Logs every HTTP request + response as a structured JSON line.

    Attaches a trace_id header (X-Trace-ID) to every response so callers can
    correlate requests across services in distributed traces.
    """

    def __init__(self, app, service_name: str = "service"):
        super().__init__(app)
        self.service_name = service_name
        self.logger = logging.getLogger(service_name)

    async def dispatch(self, request: Request, call_next: Callable) -> Response:
        trace_id = request.headers.get("X-Trace-ID", str(uuid.uuid4()))
        start = time.perf_counter()

        # Extract user_id from Bearer token (best-effort — don't fail on parse errors)
        user_id = None
        auth = request.headers.get("Authorization", "")
        if auth.startswith("Bearer "):
            try:
                import base64
                token = auth[7:]
                parts = token.split(".")
                if len(parts) == 3:
                    padded = parts[1] + "=" * (-len(parts[1]) % 4)
                    payload = json.loads(base64.urlsafe_b64decode(padded))
                    user_id = payload.get("sub")
            except Exception:
                pass

        response = await call_next(request)
        duration_ms = round((time.perf_counter() - start) * 1000, 2)

        response.headers["X-Trace-ID"] = trace_id

        level = logging.WARNING if response.status_code >= 400 else logging.INFO
        self.logger.log(
            level,
            f"{request.method} {request.url.path} → {response.status_code}",
            extra={
                "service":     self.service_name,
                "trace_id":    trace_id,
                "method":      request.method,
                "path":        request.url.path,
                "status_code": response.status_code,
                "duration_ms": duration_ms,
                "user_id":     user_id,
                "client_ip":   request.client.host if request.client else None,
            },
        )
        return response
