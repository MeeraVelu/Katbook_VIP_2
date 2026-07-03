"""API contract tests for the jobs endpoint + API-key auth enforcement."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace


def _job(**over):
    base = dict(
        job_id=uuid.uuid4(),
        video_id=uuid.uuid4(),
        state="processing",
        current_stage="visual",
        attempts=1,
        stage_timings={"ingest_audio": 0.5},
        error=None,
        enqueued_at=dt.datetime.now(dt.UTC),
        started_at=dt.datetime.now(dt.UTC),
        finished_at=None,
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_get_job_status(client, monkeypatch):
    j = _job()
    monkeypatch.setattr("app.services.jobs.get_job", lambda db, jid: j)
    monkeypatch.setattr("app.services.jobs.elapsed_seconds", lambda job: 12.3)
    r = client.get(f"/api/v1/jobs/{j.job_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["state"] == "processing"
    assert body["current_stage"] == "visual"
    assert body["elapsed_sec"] == 12.3


def test_get_job_not_found(client, monkeypatch):
    monkeypatch.setattr("app.services.jobs.get_job", lambda db, jid: None)
    r = client.get(f"/api/v1/jobs/{uuid.uuid4()}")
    assert r.status_code == 404


def test_api_key_required_when_configured(fake_session, monkeypatch):
    """With API_KEY set, a request without X-API-Key is rejected 401; with the
    correct key it passes auth."""
    from fastapi.testclient import TestClient

    from app.deps import db_session, settings_dep
    from app.main import create_app
    from app.settings import APISettings

    app = create_app()
    app.dependency_overrides[db_session] = lambda: fake_session
    app.dependency_overrides[settings_dep] = lambda: APISettings(api_key="secret")
    monkeypatch.setattr("app.services.jobs.get_job", lambda db, jid: None)
    tc = TestClient(app)

    jid = uuid.uuid4()
    assert tc.get(f"/api/v1/jobs/{jid}").status_code == 401
    # correct key -> passes auth (then 404 because get_job returns None)
    assert tc.get(f"/api/v1/jobs/{jid}", headers={"X-API-Key": "secret"}).status_code == 404


def test_health_needs_no_auth(client):
    r = client.get("/health")
    assert r.status_code == 200
    assert r.json()["status"] == "ok"
