"""API contract tests for the videos endpoints (DB + queue mocked)."""

from __future__ import annotations

import datetime as dt
import uuid
from types import SimpleNamespace


def _video(**over):
    base = dict(
        video_id=uuid.uuid4(),
        source_path="/data/inbox/x.mp4",
        status="done",
        language="en",
        has_speech=True,
        tagging_path="voice",
        duration_sec=120.0,
        file_size_bytes=1234,
        is_duplicate=False,
        canonical_video_id=None,
        content_hash="abc",
        error_message=None,
        stage_timings={"total": 3.2},
        runtime={"gpu": "RTX 5090"},
        created_at=dt.datetime.now(dt.UTC),
        updated_at=dt.datetime.now(dt.UTC),
        segments=[],
    )
    base.update(over)
    return SimpleNamespace(**base)


def _segment(**over):
    base = dict(
        seg_index=0,
        start_sec=0.0,
        end_sec=60.0,
        topic="Fractions",
        subject="Mathematics",
        grade_level="Grade 5",
        difficulty="beginner",
        content_type="lecture",
        tags=["fractions"],
        subtopics=["numerator"],
        summary="A lesson on fractions.",
        confidence=0.8,
        transcript_text="half of a whole",
        ocr="",
        extra={"scenes": ["slide presentation"], "objects": [], "captions": []},
    )
    base.update(over)
    return SimpleNamespace(**base)


def test_register_video_returns_job(client, monkeypatch):
    vid = uuid.uuid4()
    job = uuid.uuid4()
    monkeypatch.setattr(
        "api.services.videos.register_video",
        lambda db, sp, force=False: {
            "job_id": job,
            "video_id": vid,
            "status": "queued",
            "dedup": {
                "is_duplicate": False,
                "canonical_video_id": None,
                "content_hash": "abc",
                "reason": "new content",
            },
            "message": "Queued for processing.",
        },
    )
    r = client.post("/api/v1/videos", json={"source_path": "/data/inbox/x.mp4"})
    assert r.status_code == 202
    body = r.json()
    assert body["status"] == "queued"
    assert body["dedup"]["is_duplicate"] is False


def test_register_exact_duplicate(client, monkeypatch):
    vid, canon = uuid.uuid4(), uuid.uuid4()
    monkeypatch.setattr(
        "api.services.videos.register_video",
        lambda db, sp, force=False: {
            "job_id": None,
            "video_id": vid,
            "status": "duplicate",
            "dedup": {
                "is_duplicate": True,
                "canonical_video_id": canon,
                "content_hash": "abc",
                "reason": "byte-identical to an existing video",
            },
            "message": "Exact duplicate.",
        },
    )
    r = client.post("/api/v1/videos", json={"source_path": "/data/inbox/x.mp4"})
    assert r.status_code == 202
    assert r.json()["status"] == "duplicate"
    assert r.json()["job_id"] is None


def test_list_videos_paginated(client, monkeypatch):
    monkeypatch.setattr("api.services.videos.list_videos", lambda db, **k: ([_video()], 1))
    monkeypatch.setattr("api.services.videos.segment_count", lambda db, vid: 3)
    r = client.get("/api/v1/videos?page=1&page_size=10&subject=Mathematics")
    assert r.status_code == 200
    body = r.json()
    assert body["total"] == 1 and body["page"] == 1
    assert body["items"][0]["segment_count"] == 3


def test_get_video_detail(client, monkeypatch):
    v = _video(segments=[_segment()])
    monkeypatch.setattr("api.services.videos.get_video", lambda db, vid: v)
    r = client.get(f"/api/v1/videos/{v.video_id}")
    assert r.status_code == 200
    body = r.json()
    assert body["segments"][0]["scenes"] == ["slide presentation"]
    assert body["rollup"]["subject"] == "Mathematics"


def test_get_video_not_found(client, monkeypatch):
    monkeypatch.setattr("api.services.videos.get_video", lambda db, vid: None)
    r = client.get(f"/api/v1/videos/{uuid.uuid4()}")
    assert r.status_code == 404
    assert r.json()["error"]["code"] == "not_found"
    assert "request_id" in r.json()["error"]


def test_soft_delete(client, monkeypatch):
    v = _video(status="soft_deleted")
    monkeypatch.setattr("api.services.videos.soft_delete", lambda db, vid: v)
    r = client.delete(f"/api/v1/videos/{v.video_id}")
    assert r.status_code == 200
    assert r.json()["status"] == "soft_deleted"


def test_batch_enqueue(client, monkeypatch):
    monkeypatch.setattr(
        "api.services.videos.register_batch",
        lambda db, g, f, force=False: {
            "enqueued": 2,
            "duplicates": 0,
            "skipped_existing": 1,
            "total": 3,
            "items": [],
        },
    )
    r = client.post("/api/v1/videos/batch", json={"folder": "/data/inbox"})
    assert r.status_code == 202
    assert r.json()["enqueued"] == 2


def test_validation_error_envelope(client):
    r = client.post("/api/v1/videos", json={})  # missing source_path
    assert r.status_code == 422
    assert r.json()["error"]["code"] == "validation_error"
