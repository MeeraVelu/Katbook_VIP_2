"""
app/deps.py — FastAPI dependencies: DB session, API-key auth, request id.

Auth is a simple ``X-API-Key`` header check against ``API_KEY`` (this is an
internal service). If ``API_KEY`` is unset, auth is disabled (useful for local
dev / the CPU smoke run) and a warning is logged once.
"""

from __future__ import annotations

from fastapi import Depends, Header, HTTPException, Request
from sqlalchemy.orm import Session

from app.services.db import get_db
from app.settings import APISettings, get_api_settings
from katbook_vip.logging_config import get_logger

_warned = False


def db_session() -> Session:  # pragma: no cover - thin wrapper
    yield from get_db()


def settings_dep() -> APISettings:
    return get_api_settings()


async def require_api_key(
    x_api_key: str | None = Header(default=None, alias="X-API-Key"),
    settings: APISettings = Depends(settings_dep),
) -> None:
    global _warned
    if not settings.api_key:
        if not _warned:
            get_logger("app.auth").warning("API_KEY not set — authentication is DISABLED")
            _warned = True
        return
    if x_api_key != settings.api_key:
        raise HTTPException(status_code=401, detail="Invalid or missing X-API-Key")


def get_request_id(request: Request) -> str:
    return getattr(request.state, "request_id", "-")
