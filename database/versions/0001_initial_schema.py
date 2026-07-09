"""initial schema — videos, jobs, segments (UUID PKs)

Baseline migration. Every statement is guarded (CREATE TABLE IF NOT EXISTS,
ADD COLUMN IF NOT EXISTS, ...), so running it against a brand-new database
OR the already-populated production database (which was bootstrapped by the
now-retired database/postgres.py before Alembic was reinstated) produces the
same end state either way — this is what makes `alembic upgrade head` safe
to run once against live data without a manual `alembic stamp`.

Revision ID: 0001
Revises:
Create Date: 2026-07-08
"""

from __future__ import annotations

import os
from collections.abc import Sequence

from alembic import op

revision: str = "0001"
down_revision: str | Sequence[str] | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

EMBED_DIM = os.environ.get("KVIP_EMBED_DIM", "1024")

_SQL = """
CREATE EXTENSION IF NOT EXISTS vector;
CREATE EXTENSION IF NOT EXISTS pgcrypto;

-- ============================================================================
-- videos
-- ============================================================================
CREATE TABLE IF NOT EXISTS videos (
    video_id            UUID PRIMARY KEY DEFAULT gen_random_uuid()
);
COMMENT ON TABLE videos IS
    'One row per registered source video. status: queued -> done|failed. '
    'Exact-duplicate uploads (same content_hash) point canonical_video_id at '
    'the first copy instead of reprocessing.';

ALTER TABLE videos ADD COLUMN IF NOT EXISTS source_path        TEXT NOT NULL DEFAULT '';
ALTER TABLE videos ALTER COLUMN source_path DROP DEFAULT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS content_hash        TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS file_size_bytes     BIGINT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS duration_sec        DOUBLE PRECISION;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS language            TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS has_speech          BOOLEAN;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS tagging_path        TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS status              TEXT NOT NULL DEFAULT 'queued';
ALTER TABLE videos ADD COLUMN IF NOT EXISTS is_duplicate        BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS canonical_video_id  UUID REFERENCES videos(video_id);
ALTER TABLE videos ADD COLUMN IF NOT EXISTS error_message       TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS runtime             JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS stage_timings       JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS created_at          TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE videos ADD COLUMN IF NOT EXISTS updated_at          TIMESTAMPTZ NOT NULL DEFAULT now();

DO $$ BEGIN
    ALTER TABLE videos ADD CONSTRAINT videos_status_check
        CHECK (status IN ('queued','processing','done','failed','soft_deleted'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS videos_content_hash_idx ON videos(content_hash);
CREATE INDEX IF NOT EXISTS videos_status_idx        ON videos(status);
CREATE INDEX IF NOT EXISTS videos_created_at_idx    ON videos(created_at DESC);

-- ============================================================================
-- jobs
-- ============================================================================
CREATE TABLE IF NOT EXISTS jobs (
    job_id              UUID PRIMARY KEY DEFAULT gen_random_uuid()
);
COMMENT ON TABLE jobs IS
    'One row per processing ATTEMPT for a video. A forced reprocess creates a '
    'NEW job row rather than reusing the old one, so an earlier interrupted '
    'attempt is never mistaken for the current live one.';

ALTER TABLE jobs ADD COLUMN IF NOT EXISTS video_id       UUID REFERENCES videos(video_id) ON DELETE CASCADE;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS state          TEXT NOT NULL DEFAULT 'queued';
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS current_stage  TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS attempts       INT NOT NULL DEFAULT 0;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS stage_timings  JSONB NOT NULL DEFAULT '{}'::jsonb;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS error          TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS enqueued_at    TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS started_at     TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS finished_at    TIMESTAMPTZ;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS updated_at     TIMESTAMPTZ NOT NULL DEFAULT now();
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS profile        TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS progress_pct   INTEGER;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS health_score    REAL;

DO $$ BEGIN
    ALTER TABLE jobs ADD CONSTRAINT jobs_state_check
        CHECK (state IN ('queued','processing','done','failed'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS jobs_video_id_idx    ON jobs(video_id);
CREATE INDEX IF NOT EXISTS jobs_state_idx       ON jobs(state);
CREATE INDEX IF NOT EXISTS jobs_enqueued_at_idx ON jobs(enqueued_at DESC);

-- ============================================================================
-- segments
-- ============================================================================
CREATE TABLE IF NOT EXISTS segments (
    id                  UUID PRIMARY KEY DEFAULT gen_random_uuid()
);
COMMENT ON TABLE segments IS
    'One row per tagged time-range within a video. embedding is the pgvector '
    'search vector; fts is a generated tsvector for keyword/hybrid search.';

ALTER TABLE segments ADD COLUMN IF NOT EXISTS video_id         UUID REFERENCES videos(video_id) ON DELETE CASCADE;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS seg_index        INT;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS start_sec        DOUBLE PRECISION;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS end_sec          DOUBLE PRECISION;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS topic            TEXT;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS subject          TEXT;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS grade_level      TEXT;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS difficulty       TEXT;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS content_type     TEXT;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS tags             TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE segments ADD COLUMN IF NOT EXISTS subtopics        TEXT[] NOT NULL DEFAULT '{}';
ALTER TABLE segments ADD COLUMN IF NOT EXISTS summary          TEXT;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS confidence       DOUBLE PRECISION;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS transcript_text  TEXT;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS ocr              TEXT;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS extra            JSONB NOT NULL DEFAULT '{}'::jsonb;
COMMENT ON COLUMN segments.extra IS 'JSONB catch-all for the silent (no-speech) path signals: scenes, objects, captions.';

DO $$ BEGIN
    ALTER TABLE segments ADD COLUMN embedding vector(__EMBED_DIM__);
EXCEPTION WHEN duplicate_column THEN NULL; END $$;
COMMENT ON COLUMN segments.embedding IS 'pgvector embedding of the segment. Written by the pipeline only, never by the API.';

DO $$ BEGIN
    ALTER TABLE segments ADD COLUMN fts tsvector GENERATED ALWAYS AS (
        to_tsvector('simple',
            coalesce(transcript_text,'') || ' ' ||
            coalesce(summary,'') || ' ' ||
            coalesce(topic,''))
    ) STORED;
EXCEPTION WHEN duplicate_column THEN NULL; END $$;

ALTER TABLE segments ADD COLUMN IF NOT EXISTS aku_id          TEXT;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS knowledge_type  TEXT;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS bloom_level     TEXT;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS prerequisites   JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS learning_obj    JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS est_min         REAL;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS hallucination   REAL;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS review_flag     BOOLEAN NOT NULL DEFAULT FALSE;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS speakers        JSONB NOT NULL DEFAULT '[]'::jsonb;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS dominant_scene  TEXT;

DO $$ BEGIN
    ALTER TABLE segments ALTER COLUMN video_id SET NOT NULL;
EXCEPTION WHEN OTHERS THEN NULL; END $$;
DO $$ BEGIN
    ALTER TABLE segments ALTER COLUMN seg_index SET NOT NULL;
EXCEPTION WHEN OTHERS THEN NULL; END $$;
DO $$ BEGIN
    ALTER TABLE segments ALTER COLUMN start_sec SET NOT NULL;
EXCEPTION WHEN OTHERS THEN NULL; END $$;
DO $$ BEGIN
    ALTER TABLE segments ALTER COLUMN end_sec SET NOT NULL;
EXCEPTION WHEN OTHERS THEN NULL; END $$;

CREATE INDEX IF NOT EXISTS segments_video_id_idx    ON segments(video_id);
CREATE INDEX IF NOT EXISTS segments_video_seg_idx   ON segments(video_id, seg_index);
CREATE INDEX IF NOT EXISTS segments_fts_idx         ON segments USING GIN(fts);
CREATE INDEX IF NOT EXISTS segments_subject_idx     ON segments(subject);
CREATE INDEX IF NOT EXISTS segments_grade_idx       ON segments(grade_level);
CREATE INDEX IF NOT EXISTS segments_embedding_hnsw ON segments
    USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
"""


def _column_type(bind, table: str, column: str) -> str | None:
    row = bind.exec_driver_sql(
        "SELECT data_type FROM information_schema.columns "
        "WHERE table_name=%s AND column_name=%s",
        (table, column),
    ).fetchone()
    return row[0] if row else None


def _upgrade_segments_id_to_uuid(bind) -> None:
    """The one change ADD COLUMN IF NOT EXISTS can't express: an EXISTING
    segments.id column still typed bigint/bigserial. Nothing in the codebase
    reads or writes segments.id directly (verified by a full-repo grep), so
    retyping it is safe. No-ops once id is already uuid — safe to run every
    time this migration is applied (e.g. a repeated `alembic upgrade head`)."""
    current = _column_type(bind, "segments", "id")
    if current in (None, "uuid"):
        return
    bind.exec_driver_sql(
        "ALTER TABLE segments ADD COLUMN id_uuid UUID NOT NULL DEFAULT gen_random_uuid()"
    )
    bind.exec_driver_sql("ALTER TABLE segments DROP CONSTRAINT IF EXISTS segments_pkey")
    bind.exec_driver_sql("ALTER TABLE segments DROP COLUMN id")
    bind.exec_driver_sql("ALTER TABLE segments RENAME COLUMN id_uuid TO id")
    bind.exec_driver_sql("ALTER TABLE segments ADD PRIMARY KEY (id)")


def upgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql(_SQL.replace("__EMBED_DIM__", EMBED_DIM))
    _upgrade_segments_id_to_uuid(bind)


def downgrade() -> None:
    # Baseline migration — no automated downgrade (would drop production data).
    raise NotImplementedError("0001 is the baseline; downgrade not supported")
