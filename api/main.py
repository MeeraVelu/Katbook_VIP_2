"""
api/main.py — FastAPI application factory.

Wires middleware (request-id + access logging), CORS (env-configured for the
frontend origin), the consistent error envelope, the versioned routers, and the
health/ready probes. OpenAPI docs are exposed at ``/docs``. This process loads NO
ML model.
"""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from api import __version__
from api.errors import register_exception_handlers
from api.middleware import RequestContextMiddleware
from api.routers import health, jobs, search, videos
from api.settings import get_api_settings
from pipeline.logging_config import configure_logging


def create_app() -> FastAPI:
    configure_logging()
    settings = get_api_settings()

    app = FastAPI(
        title="Katbook Video Intelligence Platform API",
        version=__version__,
        description=(
            "API-first backend for the Katbook video-intelligence pipeline. "
            "Register videos, track processing jobs, and search segments by "
            "meaning or keyword. Auth: `X-API-Key` header (when `API_KEY` is set)."
        ),
        docs_url="/docs",
        redoc_url="/redoc",
        openapi_url="/openapi.json",
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origin_list,
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
        expose_headers=["X-Request-ID"],
    )
    app.add_middleware(RequestContextMiddleware)

    register_exception_handlers(app)

    app.include_router(health.router)
    app.include_router(videos.router)
    app.include_router(jobs.router)
    app.include_router(search.router)
    return app


app = create_app()
