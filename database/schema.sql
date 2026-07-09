-- database/schema.sql — REFERENCE definition of the Katbook VIP schema.
--
-- This file documents the complete, final-state schema (videos, jobs,
-- segments — every primary key a UUID) for humans to read. It is NOT applied
-- directly in production.
--
--   Production migrations: alembic upgrade head
--     (database/versions/0001_initial_schema.py + 0002_enrich_schema.py +
--      0003_cleanup_segments.py + 0004_add_updated_at_and_triggers.py — all
--      idempotent, safe against a brand-new database or an already-migrated one)
--
--   Fresh dev/test bootstrap only (skips migration history entirely):
--     psql "$DATABASE_URL" -f database/schema.sql
--
-- Whenever a new Alembic migration changes the schema, update this file to
-- match the new end state so it stays a trustworthy reference.
--
-- The vector width below (1024) matches BAAI/bge-m3, the only embedder this
-- codebase runs (asserted in worker/tasks.py::_load_worker_config) — unlike
-- the old templated {EMBED_DIM} placeholder, this file is meant to run
-- as-is via plain psql, so the value is hardcoded.

CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;   -- gen_random_uuid()

-- ============================================================================
-- videos — one row per registered source video (identity, dedup, status)
-- ============================================================================
CREATE TABLE IF NOT EXISTS videos (
    video_id            UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    source_path         TEXT NOT NULL,
    video_filename      TEXT,               -- basename(source_path), denormalized for fast display
    content_hash        TEXT,
    file_size_bytes     BIGINT,
    duration_sec        DOUBLE PRECISION,
    language            TEXT,
    has_speech          BOOLEAN,
    tagging_path        TEXT,               -- 'voice' | 'silent' — see pipeline/router.py
    profile             TEXT,               -- the KVIP_PROFILE this video was processed under
    status              TEXT NOT NULL DEFAULT 'queued',
    is_duplicate        BOOLEAN NOT NULL DEFAULT FALSE,
    canonical_video_id  UUID REFERENCES videos(video_id),
    error_message       TEXT,
    runtime             JSONB NOT NULL DEFAULT '{}'::jsonb,
    stage_timings       JSONB NOT NULL DEFAULT '{}'::jsonb,
    created_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    CONSTRAINT videos_status_check
        CHECK (status IN ('queued','processing','done','failed','soft_deleted')),
    CONSTRAINT videos_tagging_path_check
        CHECK (tagging_path IS NULL OR tagging_path IN ('voice','silent'))
);
COMMENT ON TABLE videos IS
    'One row per registered source video. status: queued -> done|failed. '
    'Exact-duplicate uploads (same content_hash) point canonical_video_id at '
    'the first copy instead of reprocessing (they get status=done, '
    'is_duplicate=TRUE — NOT a separate "duplicate" status value).';

CREATE INDEX IF NOT EXISTS videos_content_hash_idx ON videos(content_hash);
CREATE INDEX IF NOT EXISTS videos_status_idx        ON videos(status);
CREATE INDEX IF NOT EXISTS videos_created_at_idx    ON videos(created_at DESC);

-- ============================================================================
-- jobs — one row per processing ATTEMPT for a video
-- ============================================================================
CREATE TABLE IF NOT EXISTS jobs (
    job_id              UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_id            UUID REFERENCES videos(video_id) ON DELETE CASCADE,
    video_filename      TEXT,               -- basename(source_path), denormalized for fast display
    state               TEXT NOT NULL DEFAULT 'queued',
    current_stage       TEXT,
    error_stage         TEXT,               -- last reported stage at the time of failure (best-effort)
    attempts            INT NOT NULL DEFAULT 0,
    stage_timings       JSONB NOT NULL DEFAULT '{}'::jsonb,
    error               TEXT,
    enqueued_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
    started_at          TIMESTAMPTZ,
    finished_at         TIMESTAMPTZ,
    updated_at          TIMESTAMPTZ NOT NULL DEFAULT now(),
    profile             TEXT,               -- the KVIP_PROFILE this job ran under
    progress_pct        INTEGER NOT NULL DEFAULT 0,
    health_score        REAL,
    CONSTRAINT jobs_state_check
        CHECK (state IN ('queued','processing','done','failed','dead_letter'))
);
COMMENT ON TABLE jobs IS
    'One row per processing ATTEMPT for a video. A forced reprocess creates a '
    'NEW job row rather than reusing the old one, so an earlier interrupted '
    'attempt is never mistaken for the current live one.';

CREATE INDEX IF NOT EXISTS jobs_video_id_idx    ON jobs(video_id);
CREATE INDEX IF NOT EXISTS jobs_state_idx       ON jobs(state);
CREATE INDEX IF NOT EXISTS jobs_enqueued_at_idx ON jobs(enqueued_at DESC);

-- ============================================================================
-- segments — one row per tagged time-range within a video
-- ============================================================================
CREATE TABLE IF NOT EXISTS segments (
    segment_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_id             UUID NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    seg_index            INT NOT NULL,
    start_sec            DOUBLE PRECISION NOT NULL,
    end_sec              DOUBLE PRECISION NOT NULL,
    est_min              REAL,               -- opportunistic: only if the LLM/prompt returns it
    topic                TEXT,
    subject              TEXT,
    grade_level          TEXT,
    difficulty           TEXT,               -- LLM free text (beginner|intermediate|advanced|expert
                                              -- is the prompted taxonomy, but NOT enforced by a CHECK —
                                              -- the model isn't guaranteed to conform, and a violated
                                              -- CHECK would fail the whole video's storage transaction)
    content_type         TEXT,               -- LLM free text, same reasoning as difficulty above
    bloom_level          TEXT,               -- opportunistic: only if the LLM/prompt returns it
    knowledge_type       TEXT,               -- reserved: not populated by the current pipeline
    learning_objectives  JSONB DEFAULT '[]', -- opportunistic: only if the LLM/prompt returns it
    prerequisites        JSONB DEFAULT '[]', -- reserved: not populated by the current pipeline
    aku_id               TEXT,               -- reserved: not populated by the current pipeline
    tags                 TEXT[] DEFAULT '{}',
    subtopics            TEXT[] DEFAULT '{}',
    summary               TEXT,
    confidence            DOUBLE PRECISION,
    review_flag           BOOLEAN DEFAULT FALSE,
    transcript_text        TEXT,
    ocr                     TEXT,
    dominant_scene          TEXT,
    speakers                JSONB DEFAULT '[]',
    objects                 JSONB DEFAULT '[]',
    extra                   JSONB DEFAULT '{}',
    embedding                vector(1024),
    fts                      tsvector GENERATED ALWAYS AS (
        to_tsvector('simple',
            coalesce(transcript_text,'') || ' ' ||
            coalesce(summary,'') || ' ' ||
            coalesce(topic,'') || ' ' ||
            coalesce(ocr,''))
    ) STORED,
    created_at                TIMESTAMPTZ NOT NULL DEFAULT now(),
    updated_at                TIMESTAMPTZ NOT NULL DEFAULT now()
);
COMMENT ON TABLE segments IS
    'One row per tagged time-range within a video. embedding is the pgvector '
    'search vector; fts is a generated tsvector for keyword/hybrid search '
    '(transcript + summary + topic + ocr).';
COMMENT ON COLUMN segments.extra IS 'JSONB catch-all for fields with no dedicated column: scenes (full per-segment list; dominant_scene is only the single most-common value), captions, has_visual_content, and any future experimental LLM fields. Fields that DO have a dedicated column (objects, speakers, bloom_level, learning_objectives, est_min, ...) are written ONLY there, not duplicated here.';
COMMENT ON COLUMN segments.objects IS 'Detected objects for this segment. Sole source of truth (no longer duplicated inside extra).';
COMMENT ON COLUMN segments.embedding IS 'pgvector embedding of the segment. Written by the pipeline only, never by the API.';
COMMENT ON COLUMN segments.review_flag IS 'Auto-set TRUE when confidence < 0.5 or the LLM output needed truncation recovery — flags the segment for manual QA.';
COMMENT ON COLUMN segments.speakers IS 'JSON list of {role, language} derived from the LLM''s speaker_role/language fields.';
COMMENT ON COLUMN segments.dominant_scene IS 'Most frequent per-frame scene label across the segment''s frames.';
COMMENT ON COLUMN segments.aku_id IS 'Reserved: future atomic-knowledge-unit id, needs a separate curriculum-mapping design. Deliberately NEVER populated by the pipeline or the LLM.';
COMMENT ON COLUMN segments.knowledge_type IS 'Populated by the LLM: conceptual | procedural | factual | metacognitive.';
COMMENT ON COLUMN segments.bloom_level IS 'Populated only if the LLM/prompt returns it.';
COMMENT ON COLUMN segments.prerequisites IS 'Populated by the LLM: 1-3 short prior-knowledge strings, or [] if none needed. The LLM only sees one segment at a time with no curriculum context, so these are generic, not references to real prior lessons in your catalog.';
COMMENT ON COLUMN segments.learning_objectives IS 'Populated only if the LLM/prompt returns it.';
COMMENT ON COLUMN segments.est_min IS 'Populated only if the LLM/prompt returns it.';

CREATE INDEX IF NOT EXISTS segments_video_id_idx    ON segments(video_id);
CREATE INDEX IF NOT EXISTS segments_fts_idx         ON segments USING GIN(fts);
CREATE INDEX IF NOT EXISTS segments_subject_idx     ON segments(subject);
CREATE INDEX IF NOT EXISTS segments_grade_idx       ON segments(grade_level);
-- HNSW: no training step, better recall than IVFFlat at this scale. Tune
-- query-time recall with `SET hnsw.ef_search = N;`.
CREATE INDEX IF NOT EXISTS segments_embedding_hnsw ON segments
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);

-- ============================================================================
-- updated_at auto-maintenance — one shared function, one trigger per table.
-- Belt-and-suspenders: videos/jobs.updated_at is also set explicitly by
-- application code on every write, so the trigger is redundant there but
-- harmless (same now() value within the transaction); segments never had
-- application-level UPDATE support, so the trigger is what actually keeps
-- it correct if a future write path modifies a segment in place.
-- ============================================================================
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;

DROP TRIGGER IF EXISTS segments_set_updated_at ON segments;
CREATE TRIGGER segments_set_updated_at
    BEFORE UPDATE ON segments
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS videos_set_updated_at ON videos;
CREATE TRIGGER videos_set_updated_at
    BEFORE UPDATE ON videos
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();

DROP TRIGGER IF EXISTS jobs_set_updated_at ON jobs;
CREATE TRIGGER jobs_set_updated_at
    BEFORE UPDATE ON jobs
    FOR EACH ROW EXECUTE FUNCTION set_updated_at();
