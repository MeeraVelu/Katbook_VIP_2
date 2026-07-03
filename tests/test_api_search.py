"""API contract tests for the search endpoint (search service mocked) + the RRF
fusion helper (pure)."""

from __future__ import annotations

import uuid
from types import SimpleNamespace


def test_search_endpoint_shape(client, monkeypatch):
    hit = {
        "video_id": uuid.uuid4(),
        "seg_index": 0,
        "start_sec": 0.0,
        "end_sec": 60.0,
        "topic": "Pendulum",
        "subject": "Physics",
        "grade_level": "Grade 9",
        "summary": "time period",
        "score": 0.87,
    }
    monkeypatch.setattr(
        "app.services.search.search", lambda db, q, mode, limit: ("semantic", [hit])
    )
    r = client.get("/api/v1/search?q=pendulum&mode=semantic&limit=5")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "semantic" and body["count"] == 1
    assert body["results"][0]["topic"] == "Pendulum"


def test_search_degrades_to_keyword(client, monkeypatch):
    # semantic requested but embeddings unavailable -> service returns keyword
    monkeypatch.setattr("app.services.search.search", lambda db, q, mode, limit: ("keyword", []))
    r = client.get("/api/v1/search?q=oscillation&mode=semantic")
    assert r.status_code == 200
    assert r.json()["mode"] == "keyword"


def test_search_requires_query(client):
    r = client.get("/api/v1/search")
    assert r.status_code == 422


def test_rrf_fusion_ranks_common_hits_higher(monkeypatch):
    """hybrid_search fuses semantic+keyword via RRF; an item ranked well in BOTH
    lists should beat items in only one."""
    from app.services import search as svc

    def row(vid, seg):
        return SimpleNamespace(
            video_id=vid,
            seg_index=seg,
            start_sec=0,
            end_sec=10,
            topic="t",
            subject="s",
            grade_level="g",
            summary="x",
            score=1.0,
        )

    v_common, v_sem, v_kw = uuid.uuid4(), uuid.uuid4(), uuid.uuid4()
    sem = [row(v_common, 0), row(v_sem, 0)]
    kw = [row(v_common, 0), row(v_kw, 0)]

    monkeypatch.setattr(svc, "_embed_query", lambda q: [0.1] * 8)
    monkeypatch.setattr(svc, "_semantic_rows", lambda s, qv, k: sem)
    monkeypatch.setattr(svc, "_keyword_rows", lambda s, q, k: kw)

    mode, results = svc.hybrid_search(session=None, q="x", limit=3)
    assert mode == "hybrid"
    assert (results[0]["video_id"], results[0]["seg_index"]) == (v_common, 0)
