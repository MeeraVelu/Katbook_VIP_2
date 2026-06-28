"""
storage.py — Stage 6. Persist results to cloud Postgres (Neon/Supabase) as the
single durable source of truth, so a Kaggle session ending never loses data.

Idempotent: video_id is uuid5(path), so re-processing a video UPSERTs its row and
replaces its segments instead of creating duplicates. Adds `has_speech`,
`tagging_path`, and `language` so downstream tools can tell voiced from silent
results. embedding -> pgvector (semantic search); transcript -> tsvector (keyword).
"""
from __future__ import annotations
import json

from .utils import log


def make_engine(database_url: str):
    from sqlalchemy import create_engine
    return create_engine(database_url, pool_pre_ping=True)


def normalize_db_url(url: str | None) -> str | None:
    if not url:
        return None
    if url.startswith("postgres://"):
        return url.replace("postgres://", "postgresql+psycopg2://", 1)
    if url.startswith("postgresql://"):
        return url.replace("postgresql://", "postgresql+psycopg2://", 1)
    return url


def existing_video_ids(engine) -> set[str]:
    from sqlalchemy import text as sql
    try:
        with engine.connect() as cx:
            return {str(r[0]) for r in cx.execute(
                sql("SELECT DISTINCT video_id FROM videos")).fetchall()}
    except Exception:
        return set()  # tables not created yet (first run)


def _ensure_schema(cx, dim: int) -> None:
    from sqlalchemy import text as sql
    cx.execute(sql("CREATE EXTENSION IF NOT EXISTS vector"))
    cx.execute(sql("""
        CREATE TABLE IF NOT EXISTS videos (
            video_id UUID PRIMARY KEY, source_path TEXT, duration FLOAT,
            language TEXT, has_speech BOOLEAN, tagging_path TEXT,
            audio_features JSONB, nlp JSONB, stage_timings JSONB,
            created_at TIMESTAMPTZ DEFAULT now())"""))
    cx.execute(sql(f"""
        CREATE TABLE IF NOT EXISTS segments (
            id SERIAL PRIMARY KEY,
            video_id UUID REFERENCES videos(video_id) ON DELETE CASCADE,
            seg_index INT, start_sec FLOAT, end_sec FLOAT, transcript TEXT,
            scenes JSONB, objects JSONB, ocr TEXT, llm JSONB,
            embedding vector({dim}),
            fts tsvector GENERATED ALWAYS AS
                (to_tsvector('english', coalesce(transcript,'') || ' ' ||
                 coalesce(ocr,''))) STORED)"""))
    cx.execute(sql("CREATE INDEX IF NOT EXISTS seg_fts_idx ON segments USING GIN(fts)"))
    # idempotent column adds for DBs created by an earlier schema version
    for col, typ in (("has_speech", "BOOLEAN"), ("tagging_path", "TEXT")):
        cx.execute(sql(f"ALTER TABLE videos ADD COLUMN IF NOT EXISTS {col} {typ}"))


def store(payload: dict, seg_emb, engine) -> None:
    from sqlalchemy import text as sql
    dim = int(seg_emb.shape[1]) if getattr(seg_emb, "shape", [0])[0] else 384
    with engine.begin() as cx:
        _ensure_schema(cx, dim)
        cx.execute(sql("""
            INSERT INTO videos(video_id, source_path, duration, language,
                has_speech, tagging_path, audio_features, nlp, stage_timings)
            VALUES (:vid,:sp,:dur,:lang,:hs,:tp,:af,:nlp,:st)
            ON CONFLICT (video_id) DO UPDATE SET
                duration=:dur, language=:lang, has_speech=:hs, tagging_path=:tp,
                audio_features=:af, nlp=:nlp, stage_timings=:st"""),
            {"vid": payload["video_id"], "sp": payload["source_path"],
             "dur": float(payload.get("duration") or 0), "lang": payload.get("language"),
             "hs": payload.get("has_speech"), "tp": payload.get("tagging_path"),
             "af": json.dumps(payload.get("audio_features", {})),
             "nlp": json.dumps(payload.get("nlp", {})),
             "st": json.dumps(payload.get("stage_timings", {}))})
        cx.execute(sql("DELETE FROM segments WHERE video_id=:v"),
                   {"v": payload["video_id"]})
        for i, s in enumerate(payload["segments"]):
            emb = seg_emb[i].tolist() if i < len(seg_emb) else [0.0] * dim
            cx.execute(sql("""
                INSERT INTO segments(video_id, seg_index, start_sec, end_sec,
                    transcript, scenes, objects, ocr, llm, embedding)
                VALUES (:v,:i,:a,:b,:tr,:sc,:ob,:ocr,:llm,:emb)"""),
                {"v": payload["video_id"], "i": i,
                 "a": float(s["start"]), "b": float(s["end"]),
                 "tr": s.get("text", ""), "sc": json.dumps(s.get("scenes", [])),
                 "ob": json.dumps(s.get("objects", [])), "ocr": s.get("ocr", ""),
                 "llm": json.dumps(s.get("llm", {})), "emb": str(emb)})
    log(f"stored video + {len(payload['segments'])} segments in Postgres")
