"""
api/middleware.py — request-ID + structured access logging.

Assigns (or propagates) an ``X-Request-ID`` per request, binds it into the
logging context so every downstream log line carries it, echoes it back in the
response header, and logs one structured access record per request.
"""

from __future__ import annotations

import time
import uuid

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request

from pipeline.logging_config import bind, clear_context, get_logger

_log = get_logger("api.access")


class RequestContextMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        request_id = request.headers.get("X-Request-ID") or uuid.uuid4().hex[:16]
        request.state.request_id = request_id
        clear_context()
        bind(request_id=request_id)
        t0 = time.time()
        try:
            response = await call_next(request)
        except Exception:
            _log.exception(
                "request-failed",
                extra={
                    "method": request.method,
                    "path": request.url.path,
                    "duration_ms": round((time.time() - t0) * 1000, 1),
                },
            )
            clear_context()
            raise
        response.headers["X-Request-ID"] = request_id
        _log.info(
            "request",
            extra={
                "method": request.method,
                "path": request.url.path,
                "status": response.status_code,
                "duration_ms": round((time.time() - t0) * 1000, 1),
            },
        )
        clear_context()
        return response
