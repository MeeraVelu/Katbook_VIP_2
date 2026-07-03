"""
app/routers/health.py — liveness (/health) and readiness (/ready).

``/health`` is a cheap liveness probe (process is up). ``/ready`` verifies the
service can actually do work: Postgres reachable, Redis reachable, and — because
all GPU work is on the worker — that a worker has published a recent GPU heartbeat
(see worker/heartbeat.py). Readiness on GPU visibility can be disabled with
``READY_REQUIRES_GPU=0`` for CPU/dev deployments.
"""

from __future__ import annotations

import time

from fastapi import APIRouter, Response
from sqlalchemy import text

from app import __version__
from app.schemas.common import HealthResponse, ReadyResponse
from app.settings import get_api_settings

router = APIRouter(tags=["health"])

HEARTBEAT_KEY = "katbook:worker:heartbeat"
HEARTBEAT_MAX_AGE_S = 60


@router.get("/health", response_model=HealthResponse)
def health() -> HealthResponse:
    return HealthResponse(status="ok", version=__version__)


@router.get("/ready", response_model=ReadyResponse)
def ready(response: Response) -> ReadyResponse:
    s = get_api_settings()
    checks: dict[str, bool] = {}
    details: dict = {}

    # Postgres
    try:
        from app.services.db import get_engine

        with get_engine().connect() as cx:
            cx.execute(text("SELECT 1"))
        checks["database"] = True
    except Exception as e:
        checks["database"] = False
        details["database_error"] = str(e)[:200]

    # Redis + worker GPU heartbeat
    gpu_ok = True
    try:
        import redis

        r = redis.Redis.from_url(s.redis_url)
        r.ping()
        checks["redis"] = True
        hb = r.get(HEARTBEAT_KEY)
        if s.require_gpu_heartbeat_for_ready:
            age = (time.time() - float(hb)) if hb else None
            gpu_ok = age is not None and age <= HEARTBEAT_MAX_AGE_S
            checks["worker_gpu"] = gpu_ok
            details["heartbeat_age_s"] = round(age, 1) if age is not None else None
    except Exception as e:
        checks["redis"] = False
        checks["worker_gpu"] = not s.require_gpu_heartbeat_for_ready
        details["redis_error"] = str(e)[:200]

    ready_flag = all(checks.values())
    if not ready_flag:
        response.status_code = 503
    return ReadyResponse(ready=ready_flag, checks=checks, details=details)
