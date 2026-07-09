"""
storage.py — Stage 6. Persist results to Postgres (the single source of truth).

Production changes vs the POC:
  * **No inline DDL.** The schema is owned by Alembic (``database/versions``); this
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
import os

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
    # duplicated-elsewhere fields: each has its own dedicated column (or is
    # folded into `speakers`), so they're excluded from `extra` too — see
    # _seg_columns below.
    "est_min",
    "objects",
    "language",
    "bloom_level",
    "speaker_role",
    "learning_objectives",
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
            INSERT INTO videos(video_id, source_path, video_filename, content_hash,
                file_size_bytes, status, is_duplicate, canonical_video_id, updated_at)
            VALUES (:vid,:sp,:vf,:h,:fs,'done',TRUE,:can, now())
            ON CONFLICT (video_id) DO UPDATE SET
                is_duplicate=TRUE, canonical_video_id=:can, content_hash=:h,
                status='done', updated_at=now()"""),
            {
                "vid": video_id,
                "sp": source_path,
                "vf": os.path.basename(source_path) if source_path else None,
                "h": content_hash,
                "fs": file_size,
                "can": canonical_id,
            },
        )
    log(f"duplicate recorded -> canonical {canonical_id[:8]} (no reprocessing)")


def _seg_columns(seg: dict, emb_list) -> dict:
    """Project one in-memory segment into the structured row for insertion."""
    llm = seg.get("llm", {}) or {}
    # `extra` holds ONLY fields with no dedicated column: the full per-frame
    # scenes list (dominant_scene is just the single most-common value, not a
    # replacement), captions, has_visual_content, and any future experimental
    # LLM field. Fields with a dedicated column (objects, speakers/speaker_role,
    # language, bloom_level, learning_objectives, est_min, ...) are excluded via
    # _CORE_LLM_FIELDS and written ONLY to their own column, never duplicated here.
    extra = {k: v for k, v in llm.items() if k not in _CORE_LLM_FIELDS}
    extra.update(
        {
            "scenes": seg.get("scenes", []),
            "captions": seg.get("captions", []),
            "has_visual_content": llm.get("has_visual_content"),
        }
    )
    objects = seg.get("objects", []) or []
    conf = llm.get("confidence")
    conf_val = float(conf) if isinstance(conf, (int, float)) else None

    speaker_role = llm.get("speaker_role")
    speakers = [{"role": speaker_role, "language": llm.get("language")}] if speaker_role else []

    # enrichment: populated opportunistically — only if the LLM/pipeline
    # actually produced a value; the current prompt doesn't ask for
    # prerequisites, so it stays [] until a future prompt change adds it.
    review_flag = bool(llm.get("_recovered")) or (conf_val is not None and conf_val < 0.5)

    return {
        "topic": llm.get("topic"),
        "subject": llm.get("subject"),
        "grade_level": llm.get("grade_level"),
        "difficulty": llm.get("difficulty"),
        "content_type": llm.get("content_type"),
        "tags": list(llm.get("tags", []) or []),
        "subtopics": list(llm.get("subtopics", []) or []),
        "summary": llm.get("summary"),
        "confidence": conf_val,
        "transcript_text": seg.get("text", "") or "",
        "ocr": seg.get("ocr", "") or "",
        "extra": json.dumps(extra, default=str),
        "embedding": "[" + ",".join(f"{x:.6f}" for x in emb_list) + "]",
        "objects": json.dumps(objects, default=str),
        "speakers": json.dumps(speakers, default=str),
        "dominant_scene": seg.get("dominant_scene"),
        "review_flag": review_flag,
        "bloom_level": llm.get("bloom_level"),
        "prerequisites": json.dumps(llm.get("prerequisites") or [], default=str),
        "learning_objectives": json.dumps(llm.get("learning_objectives") or [], default=str),
        "est_min": llm.get("est_min"),
        "aku_id": llm.get("aku_id"),
        "knowledge_type": llm.get("knowledge_type"),
    }


def store(payload: dict, seg_emb, engine) -> None:
    """Idempotently upsert the video + replace its segments (structured columns)."""
    from sqlalchemy import text as sql

    with engine.begin() as cx:
        cx.execute(
            sql("""
            INSERT INTO videos(video_id, source_path, video_filename, content_hash,
                file_size_bytes, duration_sec, language, has_speech, tagging_path,
                profile, status, is_duplicate, canonical_video_id, error_message,
                runtime, stage_timings, updated_at)
            VALUES (:vid,:sp,:vf,:ch,:fs,:dur,:lang,:hs,:tp,:pf,'done',
                FALSE,NULL,NULL, CAST(:rt AS jsonb), CAST(:st AS jsonb), now())
            ON CONFLICT (video_id) DO UPDATE SET
                source_path=:sp, video_filename=:vf, content_hash=:ch, file_size_bytes=:fs,
                duration_sec=:dur, language=:lang, has_speech=:hs, tagging_path=:tp,
                profile=:pf, status='done', is_duplicate=FALSE, canonical_video_id=NULL,
                error_message=NULL, runtime=CAST(:rt AS jsonb),
                stage_timings=CAST(:st AS jsonb), updated_at=now()"""),
            {
                "vid": payload["video_id"],
                "sp": payload["source_path"],
                "vf": os.path.basename(payload["source_path"]) if payload.get("source_path") else None,
                "ch": payload.get("content_hash"),
                "fs": payload.get("file_size_bytes"),
                "dur": float(payload.get("duration") or 0),
                "lang": payload.get("language"),
                "hs": payload.get("has_speech"),
                "tp": payload.get("tagging_path"),
                "pf": payload.get("runtime", {}).get("profile"),
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
                    extra, embedding, objects, speakers, dominant_scene, review_flag,
                    bloom_level, prerequisites, learning_objectives, est_min,
                    aku_id, knowledge_type)
                VALUES (:v,:i,:a,:b,:topic,:subject,:grade_level,:difficulty,
                    :content_type,:tags,:subtopics,:summary,:confidence,
                    :transcript_text,:ocr, CAST(:extra AS jsonb),
                    CAST(:embedding AS vector), CAST(:objects AS jsonb),
                    CAST(:speakers AS jsonb), :dominant_scene, :review_flag,
                    :bloom_level, CAST(:prerequisites AS jsonb),
                    CAST(:learning_objectives AS jsonb), :est_min,
                    :aku_id, :knowledge_type)"""),
                {
                    "v": payload["video_id"],
                    "i": i,
                    "a": float(s["start"]),
                    "b": float(s["end"]),
                    **cols,
                },
            )
    log(f"stored video + {len(payload['segments'])} segments in Postgres")
