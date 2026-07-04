"""
Shared test fixtures. Everything here runs on CPU with NO GPU and NO real models
or database — the pipeline's heavy pieces are mocked. API tests use FastAPI's
TestClient with the DB session + auth dependencies overridden and the Celery
enqueue patched out (a fake queue).
"""

from __future__ import annotations

import os
from unittest.mock import MagicMock

import pytest

# Deterministic, DB-free defaults for the whole test session.
os.environ.setdefault("DATABASE_URL", "postgresql://u:p@localhost/none")
os.environ.setdefault("API_KEY", "")  # auth disabled unless a test overrides
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("EMBEDDINGS_URL", "")  # keyword fallback in search tests
# NOTE: deliberately do NOT set KVIP_EMBED_DIM here — it would clash with the
# fast/smoke profiles' 384-d embedder (the fail-fast validation working). The API
# ORM gets its vector width from APISettings.embed_dim (default 1024) instead.

# Isolate tests from any local `.env` in the repo root (e.g. a real compose .env
# used for `docker compose`): its production values would otherwise leak into the
# profiles under test. pydantic-settings reads model_config["env_file"] at init.
from pipeline.settings import Settings as _PipelineSettings  # noqa: E402

_PipelineSettings.model_config["env_file"] = None
try:
    from api.settings import APISettings as _APISettings  # noqa: E402

    _APISettings.model_config["env_file"] = None
except Exception:
    pass


@pytest.fixture
def fake_session() -> MagicMock:
    """A stand-in SQLAlchemy Session; individual tests set return values."""
    return MagicMock(name="Session")


@pytest.fixture
def client(fake_session, monkeypatch):
    """FastAPI TestClient with DB + auth dependencies overridden and enqueue faked."""
    from fastapi.testclient import TestClient

    from api.deps import db_session, require_api_key
    from api.main import create_app

    # never actually enqueue to Redis during tests
    monkeypatch.setattr("api.services.videos.enqueue_video", lambda *a, **k: None)

    app = create_app()
    app.dependency_overrides[db_session] = lambda: fake_session
    app.dependency_overrides[require_api_key] = lambda: None
    return TestClient(app)
