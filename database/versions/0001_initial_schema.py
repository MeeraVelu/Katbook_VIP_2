"""initial production schema: videos, segments, jobs + pgvector/HNSW/GIN indexes

Revision ID: 0001_initial
Revises:
Create Date: 2026-07-03

The embedding column width comes from $KVIP_EMBED_DIM (default 1024 for BGE-M3),
so a deployment that deliberately keeps a 384-d embedder migrates to vector(384).
It is validated against the embedder at pipeline startup (see settings.Settings).
"""
from __future__ import annotations

import os

from alembic import op

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None

EMBED_DIM = int(os.environ.get("KVIP_EMBED_DIM", "1024"))


def upgrade() -> None:
    op.execute("CREATE EXTENSION IF NOT EXISTS vector")

    # ----------------------------- videos ---------------------------------- #
    op.execute("""
        CREATE TABLE videos (
            video_id           UUID PRIMARY KEY,
            source_path        TEXT NOT NULL,
            content_hash       TEXT,
            file_size_bytes    BIGINT,
            duration_sec       DOUBLE PRECISION,
            language           TEXT,
            has_speech         BOOLEAN,
            tagging_path       TEXT,
            status             TEXT NOT NULL DEFAULT 'queued',
            is_duplicate       BOOLEAN NOT NULL DEFAULT FALSE,
            canonical_video_id UUID REFERENCES videos(video_id),
            error_message      TEXT,
            runtime            JSONB NOT NULL DEFAULT '{}'::jsonb,
            stage_timings      JSONB NOT NULL DEFAULT '{}'::jsonb,
            created_at         TIMESTAMPTZ NOT NULL DEFAULT now(),
            updated_at         TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX videos_content_hash_idx ON videos(content_hash)")
    op.execute("CREATE INDEX videos_status_idx ON videos(status)")

    # ----------------------------- segments -------------------------------- #
    op.execute(f"""
        CREATE TABLE segments (
            id              BIGSERIAL PRIMARY KEY,
            video_id        UUID NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
            seg_index       INT NOT NULL,
            start_sec       DOUBLE PRECISION NOT NULL,
            end_sec         DOUBLE PRECISION NOT NULL,
            topic           TEXT,
            subject         TEXT,
            grade_level     TEXT,
            difficulty      TEXT,
            content_type    TEXT,
            tags            TEXT[] NOT NULL DEFAULT '{{}}',
            subtopics       TEXT[] NOT NULL DEFAULT '{{}}',
            summary         TEXT,
            confidence      DOUBLE PRECISION,
            transcript_text TEXT,
            ocr             TEXT,
            extra           JSONB NOT NULL DEFAULT '{{}}'::jsonb,
            embedding       vector({EMBED_DIM}),
            fts             tsvector GENERATED ALWAYS AS (
                                to_tsvector('simple',
                                    coalesce(transcript_text,'') || ' ' ||
                                    coalesce(summary,'') || ' ' ||
                                    coalesce(topic,''))
                            ) STORED
        )
    """)
    op.execute("CREATE INDEX segments_video_id_idx ON segments(video_id)")
    op.execute("CREATE INDEX segments_fts_idx ON segments USING GIN(fts)")
    op.execute("CREATE INDEX segments_subject_idx ON segments(subject)")
    op.execute("CREATE INDEX segments_grade_idx ON segments(grade_level)")
    # HNSW (no training step, better recall than IVFFlat for ~1M rows from 95k
    # videos). Tune query-time recall with `SET hnsw.ef_search = N;` (see DATABASE.md).
    op.execute(
        "CREATE INDEX segments_embedding_hnsw ON segments "
        "USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64)")

    # ------------------------------- jobs ---------------------------------- #
    op.execute("""
        CREATE TABLE jobs (
            job_id        UUID PRIMARY KEY,
            video_id      UUID REFERENCES videos(video_id) ON DELETE CASCADE,
            state         TEXT NOT NULL DEFAULT 'queued',
            current_stage TEXT,
            attempts      INT NOT NULL DEFAULT 0,
            stage_timings JSONB NOT NULL DEFAULT '{}'::jsonb,
            error         TEXT,
            enqueued_at   TIMESTAMPTZ NOT NULL DEFAULT now(),
            started_at    TIMESTAMPTZ,
            finished_at   TIMESTAMPTZ,
            updated_at    TIMESTAMPTZ NOT NULL DEFAULT now()
        )
    """)
    op.execute("CREATE INDEX jobs_video_id_idx ON jobs(video_id)")
    op.execute("CREATE INDEX jobs_state_idx ON jobs(state)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS jobs")
    op.execute("DROP TABLE IF EXISTS segments")
    op.execute("DROP TABLE IF EXISTS videos")
