"""
storage.py — Stage 6. Persist results to Postgres (the single source of truth).

Production changes vs the POC:
  * **No inline DDL.** The schema is owned by Alembic (``alembic/versions``); this
    module assumes it exists. (The POC's ``CREATE TABLE IF NOT EXISTS`` /
    ``ADD COLUMN`` calls are gone.)
  * **Structured segment columns.** The per-segment LLM JSON is projected into
    typed columns (topic/subject/grade_level/difficulty/content_type/tags[]/
    subtopics[]/summary/confidence/transcript_text) for clean filtering + search,
    with the remaining fields and the visual signals kept in ``extra`` (jsonb) and
    ``ocr`` so the exact export JSON can still be reconstructed losslessly.
  * **psycopg v3** driver by default.

PRESERVED behavior:
  * ``video_id = uuid5(path)`` idempotent UPSERT (re-run replaces, never duplicates).
  * Exact-duplicate (SHA-256) detection: a byte-identical re-upload is stored as a
    reference to its canonical (``is_duplicate``/``canonical_video_id``) and never
    reprocessed. Same-topic/different-content videos are NEVER merged or deleted.
"""

from __future__ import annotations

import json

from .utils import log

# LLM fields that get their own typed column; everything else goes to ``extra``.
_CORE_LLM_FIELDS = {
    "topic",
    "subject",
    "grade_level",
    "difficulty",
    "content_type",
    "tags",
    "subtopics",
    "summary",
    "confidence",
}


def make_engine(database_url: str):
    from sqlalchemy import create_engine

    return create_engine(database_url, pool_pre_ping=True, future=True)


def normalize_db_url(url: str | None) -> str | None:
    """Return a SQLAlchemy URL using the psycopg (v3) driver. A bare
    ``postgres://``/``postgresql://`` (as Neon/Supabase hand out) is rewritten."""
    if not url:
        return None
    if url.startswith("postgresql+"):  # already driver-qualified
        return url
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg://", 1)
    return url


def existing_video_ids(engine) -> set[str]:
    from sqlalchemy import text as sql

    try:
        with engine.connect() as cx:
            return {
                str(r[0])
                for r in cx.execute(sql("SELECT DISTINCT video_id FROM videos")).fetchall()
            }
    except Exception:
        return set()  # table absent (migration not yet run) -> treat as empty


def find_canonical_by_hash(engine, content_hash: str, exclude_id: str) -> str | None:
    """Return the video_id of an already-stored, NON-duplicate, non-soft-deleted
    video with the same file hash (the canonical), or None. Lets us skip
    re-processing an exact re-upload."""
    if not content_hash:
        return None
    from sqlalchemy import text as sql

    try:
        with engine.connect() as cx:
            row = cx.execute(
                sql(
                    "SELECT video_id FROM videos WHERE content_hash=:h "
                    "AND COALESCE(is_duplicate, FALSE)=FALSE "
                    "AND status <> 'soft_deleted' AND video_id<>:vid "
                    "ORDER BY created_at LIMIT 1"
                ),
                {"h": content_hash, "vid": exclude_id},
            ).first()
        return str(row[0]) if row else None
    except Exception:
        return None


def store_duplicate(
    engine,
    video_id: str,
    source_path: str,
    content_hash: str,
    canonical_id: str,
    file_size: int | None = None,
) -> None:
    """Record a duplicate as a lightweight videos row pointing at its canonical,
    WITHOUT segments (the canonical already holds them)."""
    from sqlalchemy import text as sql

    with engine.begin() as cx:
        cx.execute(
            sql("""
            INSERT INTO videos(video_id, source_path, content_hash, file_size_bytes,
                status, is_duplicate, canonical_video_id, updated_at)
            VALUES (:vid,:sp,:h,:fs,'done',TRUE,:can, now())
            ON CONFLICT (video_id) DO UPDATE SET
                is_duplicate=TRUE, canonical_video_id=:can, content_hash=:h,
                status='done', updated_at=now()"""),
            {
                "vid": video_id,
                "sp": source_path,
                "h": content_hash,
                "fs": file_size,
                "can": canonical_id,
            },
        )
    log(f"duplicate recorded -> canonical {canonical_id[:8]} (no reprocessing)")


def _seg_columns(seg: dict, emb_list) -> dict:
    """Project one in-memory segment into the structured row for insertion."""
    llm = seg.get("llm", {}) or {}
    extra = {k: v for k, v in llm.items() if k not in _CORE_LLM_FIELDS}
    # visual evidence lives in extra so the silent-path record + export stay lossless
    extra.update(
        {
            "scenes": seg.get("scenes", []),
            "objects": seg.get("objects", []),
            "captions": seg.get("captions", []),
        }
    )
    conf = llm.get("confidence")
    return {
        "topic": llm.get("topic"),
        "subject": llm.get("subject"),
        "grade_level": llm.get("grade_level"),
        "difficulty": llm.get("difficulty"),
        "content_type": llm.get("content_type"),
        "tags": list(llm.get("tags", []) or []),
        "subtopics": list(llm.get("subtopics", []) or []),
        "summary": llm.get("summary"),
        "confidence": float(conf) if isinstance(conf, (int, float)) else None,
        "transcript_text": seg.get("text", "") or "",
        "ocr": seg.get("ocr", "") or "",
        "extra": json.dumps(extra, default=str),
        "embedding": "[" + ",".join(f"{x:.6f}" for x in emb_list) + "]",
    }


def store(payload: dict, seg_emb, engine) -> None:
    """Idempotently upsert the video + replace its segments (structured columns)."""
    from sqlalchemy import text as sql

    with engine.begin() as cx:
        cx.execute(
            sql("""
            INSERT INTO videos(video_id, source_path, content_hash, file_size_bytes,
                duration_sec, language, has_speech, tagging_path, status,
                is_duplicate, canonical_video_id, error_message,
                runtime, stage_timings, updated_at)
            VALUES (:vid,:sp,:ch,:fs,:dur,:lang,:hs,:tp,'done',
                FALSE,NULL,NULL, CAST(:rt AS jsonb), CAST(:st AS jsonb), now())
            ON CONFLICT (video_id) DO UPDATE SET
                source_path=:sp, content_hash=:ch, file_size_bytes=:fs,
                duration_sec=:dur, language=:lang, has_speech=:hs, tagging_path=:tp,
                status='done', is_duplicate=FALSE, canonical_video_id=NULL,
                error_message=NULL, runtime=CAST(:rt AS jsonb),
                stage_timings=CAST(:st AS jsonb), updated_at=now()"""),
            {
                "vid": payload["video_id"],
                "sp": payload["source_path"],
                "ch": payload.get("content_hash"),
                "fs": payload.get("file_size_bytes"),
                "dur": float(payload.get("duration") or 0),
                "lang": payload.get("language"),
                "hs": payload.get("has_speech"),
                "tp": payload.get("tagging_path"),
                "rt": json.dumps(payload.get("runtime", {}), default=str),
                "st": json.dumps(payload.get("stage_timings", {}), default=str),
            },
        )

        cx.execute(sql("DELETE FROM segments WHERE video_id=:v"), {"v": payload["video_id"]})
        for i, s in enumerate(payload["segments"]):
            emb = (
                seg_emb[i].tolist()
                if i < len(seg_emb)
                else [0.0]
                * (
                    int(seg_emb.shape[1])
                    if getattr(seg_emb, "shape", None) is not None and len(seg_emb.shape) == 2
                    else 1024
                )
            )
            cols = _seg_columns(s, emb)
            cx.execute(
                sql("""
                INSERT INTO segments(video_id, seg_index, start_sec, end_sec,
                    topic, subject, grade_level, difficulty, content_type,
                    tags, subtopics, summary, confidence, transcript_text, ocr,
                    extra, embedding)
                VALUES (:v,:i,:a,:b,:topic,:subject,:grade_level,:difficulty,
                    :content_type,:tags,:subtopics,:summary,:confidence,
                    :transcript_text,:ocr, CAST(:extra AS jsonb),
                    CAST(:embedding AS vector))"""),
                {
                    "v": payload["video_id"],
                    "i": i,
                    "a": float(s["start"]),
                    "b": float(s["end"]),
                    **cols,
                },
            )
    log(f"stored video + {len(payload['segments'])} segments in Postgres")
