"""
app/errors.py — consistent error envelope + exception handlers.

Every non-2xx response is ``{"error": {"code", "message", "request_id", "details"}}``
(see :class:`app.schemas.common.ErrorResponse`). Handlers translate FastAPI/HTTP
errors, validation errors, the service-layer ``VideoError``, and any unhandled
exception into that shape.
"""

from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from starlette.exceptions import HTTPException as StarletteHTTPException

from app.services.videos import VideoError
from katbook_vip.logging_config import get_logger

_STATUS_CODE = {
    400: "bad_request",
    401: "unauthorized",
    403: "forbidden",
    404: "not_found",
    409: "conflict",
    422: "validation_error",
    429: "rate_limited",
    500: "internal_error",
    503: "unavailable",
}


def _envelope(
    request: Request,
    status: int,
    message: str,
    code: str | None = None,
    details: dict | None = None,
) -> JSONResponse:
    body = {
        "error": {
            "code": code or _STATUS_CODE.get(status, "error"),
            "message": message,
            "request_id": getattr(request.state, "request_id", None),
            "details": details,
        }
    }
    return JSONResponse(status_code=status, content=body)


def register_exception_handlers(app: FastAPI) -> None:
    log = get_logger("app.errors")

    @app.exception_handler(VideoError)
    async def _video_error(request: Request, exc: VideoError):
        status = 404 if exc.code == "not_found" else 400
        return _envelope(request, status, str(exc), code=exc.code)

    @app.exception_handler(StarletteHTTPException)
    async def _http_error(request: Request, exc: StarletteHTTPException):
        return _envelope(request, exc.status_code, str(exc.detail))

    @app.exception_handler(RequestValidationError)
    async def _validation_error(request: Request, exc: RequestValidationError):
        return _envelope(
            request, 422, "Request validation failed", details={"errors": exc.errors()}
        )

    @app.exception_handler(Exception)
    async def _unhandled(request: Request, exc: Exception):
        log.exception("unhandled error", extra={"path": request.url.path})
        return _envelope(request, 500, "Internal server error")
