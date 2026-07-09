"""
Storage idempotency + exact-duplicate behavior against a REAL Postgres.

Integration test: skipped unless ``KVIP_TEST_DATABASE_URL`` points at a disposable
pgvector database (e.g. the compose `postgres` service). It wipes the schema and
reapplies the Alembic migrations fresh, then verifies:
  * re-storing the same video UPSERTs (one video row, segments replaced not doubled);
  * a byte-identical file is recorded as a duplicate reference to its canonical.

Run locally:
    docker compose up -d postgres
    KVIP_TEST_DATABASE_URL=postgresql://katbook:change-me-strong@localhost:5432/katbook \
        pytest tests/test_storage_idempotency.py -m integration
"""

from __future__ import annotations

import os
import uuid

import numpy as np
import pytest

TEST_URL = os.environ.get("KVIP_TEST_DATABASE_URL")
pytestmark = pytest.mark.integration

if not TEST_URL:
    pytest.skip(
        "set KVIP_TEST_DATABASE_URL to run storage integration tests", allow_module_level=True
    )

from pipeline.storage import (  # noqa: E402
    find_canonical_by_hash,
    make_engine,
    normalize_db_url,
    store,
    store_duplicate,
)


@pytest.fixture(scope="module")
def engine():
    os.environ["DATABASE_URL"] = TEST_URL
    os.environ.setdefault("KVIP_EMBED_DIM", "1024")
    import psycopg
    from alembic import command
    from alembic.config import Config

    scheme, rest = TEST_URL.split("://", 1)
    dsn = f"{scheme.split('+', 1)[0]}://{rest}"
    with psycopg.connect(dsn, connect_timeout=15) as cx:
        cx.execute("DROP SCHEMA public CASCADE; CREATE SCHEMA public;")
        cx.commit()

    repo_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    cfg = Config(os.path.join(repo_root, "alembic.ini"))
    command.upgrade(cfg, "head")

    eng = make_engine(normalize_db_url(TEST_URL))
    yield eng
    eng.dispose()


def _payload(vid: str, path: str, content_hash: str, n_segments: int = 2) -> dict:
    return {
        "video_id": vid,
        "source_path": path,
        "content_hash": content_hash,
        "file_size_bytes": 111,
        "duration": 120.0,
        "language": "en",
        "has_speech": True,
        "tagging_path": "voice",
        "runtime": {"gpu": "test"},
        "stage_timings": {"total": 1.0},
        "segments": [
            {
                "start": i * 60,
                "end": (i + 1) * 60,
                "text": f"segment {i}",
                "ocr": "",
                "scenes": ["slide presentation"],
                "objects": [],
                "captions": [],
                "llm": {
                    "topic": f"Topic {i}",
                    "subject": "Mathematics",
                    "grade_level": "Grade 5",
                    "difficulty": "beginner",
                    "content_type": "lecture",
                    "tags": ["t"],
                    "subtopics": ["s"],
                    "summary": f"summary {i}",
                    "confidence": 0.8,
                    "speaker_role": "teacher",
                    "language": "en",
                },
            }
            for i in range(n_segments)
        ],
    }


def _count(engine, sql, params):
    from sqlalchemy import text

    with engine.connect() as cx:
        return cx.execute(text(sql), params).scalar_one()


def test_upsert_is_idempotent(engine):
    vid = str(uuid.uuid4())
    emb = np.ones((2, 1024), dtype="float32")
    p = _payload(vid, "/data/inbox/lesson.mp4", "hash-A")

    store(p, emb, engine)
    store(p, emb, engine)  # re-run must not duplicate

    assert _count(engine, "SELECT count(*) FROM videos WHERE video_id=:v", {"v": vid}) == 1
    assert _count(engine, "SELECT count(*) FROM segments WHERE video_id=:v", {"v": vid}) == 2
    # structured columns are populated
    topic = _count(
        engine,
        "SELECT count(*) FROM segments WHERE video_id=:v AND subject='Mathematics'",
        {"v": vid},
    )
    assert topic == 2


def test_exact_duplicate_references_canonical(engine):
    canonical = str(uuid.uuid4())
    dup = str(uuid.uuid4())
    emb = np.ones((1, 1024), dtype="float32")
    store(_payload(canonical, "/data/inbox/orig.mp4", "hash-DUP", n_segments=1), emb, engine)

    found = find_canonical_by_hash(engine, "hash-DUP", dup)
    assert found == canonical

    store_duplicate(engine, dup, "/data/inbox/copy.mp4", "hash-DUP", canonical, file_size=222)
    is_dup = _count(
        engine,
        "SELECT count(*) FROM videos WHERE video_id=:v AND is_duplicate=TRUE "
        "AND canonical_video_id=:c",
        {"v": dup, "c": canonical},
    )
    assert is_dup == 1
    # the duplicate has NO segments (canonical holds them) — safety/compute saving
    assert _count(engine, "SELECT count(*) FROM segments WHERE video_id=:v", {"v": dup}) == 0
