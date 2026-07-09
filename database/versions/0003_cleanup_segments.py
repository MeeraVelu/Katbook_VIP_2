"""cleanup segments — segment_id rename, drop hallucination, reorder columns

Rebuilds the segments table (rename-old -> create-new -> copy -> drop-old,
since Postgres can't reorder columns or rename a PK column used by FK-less
downstream code in a single ALTER):

  * id -> segment_id (consistency with videos.video_id / jobs.job_id)
  * drops the redundant hallucination column
  * reorders columns for readability (segment_id first, related fields grouped)
  * fts is regenerated (STORED generated columns can't be copied by value)

aku_id / knowledge_type / prerequisites are KEPT (still reserved, still
nullable/defaulted, still not populated by the current pipeline).

Guarded: a rerun after this has already applied (segments.segment_id already
exists) is a no-op, matching the idempotency of 0001/0002.

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | Sequence[str] | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_NEW_COLUMNS = """
    segment_id           UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_id             UUID NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    seg_index            INT NOT NULL,
    start_sec            DOUBLE PRECISION NOT NULL,
    end_sec              DOUBLE PRECISION NOT NULL,
    est_min              REAL,
    topic                TEXT,
    subject              TEXT,
    grade_level          TEXT,
    difficulty           TEXT,
    content_type         TEXT,
    bloom_level          TEXT,
    knowledge_type       TEXT,
    learning_objectives  JSONB DEFAULT '[]',
    prerequisites        JSONB DEFAULT '[]',
    aku_id               TEXT,
    tags                 TEXT[] DEFAULT '{}',
    subtopics            TEXT[] DEFAULT '{}',
    summary              TEXT,
    confidence           DOUBLE PRECISION,
    review_flag          BOOLEAN DEFAULT FALSE,
    transcript_text      TEXT,
    ocr                  TEXT,
    dominant_scene       TEXT,
    speakers             JSONB DEFAULT '[]',
    objects              JSONB DEFAULT '[]',
    extra                JSONB DEFAULT '{}',
    embedding            vector(1024),
    fts                  tsvector GENERATED ALWAYS AS (
        to_tsvector('simple',
            coalesce(transcript_text, '') || ' ' ||
            coalesce(summary, '') || ' ' ||
            coalesce(topic, '') || ' ' ||
            coalesce(ocr, ''))
    ) STORED,
    created_at           TIMESTAMPTZ NOT NULL DEFAULT now()
"""

# Columns copied 1:1 from the old table (everything except id->segment_id,
# hallucination (dropped), and fts (regenerated, can't be inserted directly).
_COPY_COLUMNS = (
    "video_id, seg_index, start_sec, end_sec, est_min, topic, subject, "
    "grade_level, difficulty, content_type, bloom_level, knowledge_type, "
    "learning_objectives, prerequisites, aku_id, tags, subtopics, summary, "
    "confidence, review_flag, transcript_text, ocr, dominant_scene, "
    "speakers, objects, extra, embedding"
)

_OLD_COLUMNS = """
    id                   UUID PRIMARY KEY DEFAULT gen_random_uuid(),
    video_id             UUID NOT NULL REFERENCES videos(video_id) ON DELETE CASCADE,
    seg_index            INT NOT NULL,
    start_sec            DOUBLE PRECISION NOT NULL,
    end_sec              DOUBLE PRECISION NOT NULL,
    topic                TEXT,
    subject              TEXT,
    grade_level          TEXT,
    difficulty           TEXT,
    content_type         TEXT,
    tags                 TEXT[] NOT NULL DEFAULT '{}',
    subtopics            TEXT[] NOT NULL DEFAULT '{}',
    summary              TEXT,
    confidence           DOUBLE PRECISION,
    transcript_text      TEXT,
    ocr                  TEXT,
    extra                JSONB NOT NULL DEFAULT '{}'::jsonb,
    embedding            vector(1024),
    fts                  tsvector GENERATED ALWAYS AS (
        to_tsvector('simple',
            coalesce(transcript_text, '') || ' ' ||
            coalesce(summary, '') || ' ' ||
            coalesce(topic, '') || ' ' ||
            coalesce(ocr, ''))
    ) STORED,
    aku_id               TEXT,
    knowledge_type       TEXT,
    bloom_level          TEXT,
    prerequisites        JSONB NOT NULL DEFAULT '[]'::jsonb,
    learning_objectives  JSONB NOT NULL DEFAULT '[]'::jsonb,
    est_min              REAL,
    hallucination        REAL,
    review_flag          BOOLEAN NOT NULL DEFAULT FALSE,
    speakers             JSONB NOT NULL DEFAULT '[]'::jsonb,
    dominant_scene       TEXT,
    objects              JSONB NOT NULL DEFAULT '[]'::jsonb
"""


def _already_migrated(bind) -> bool:
    row = bind.exec_driver_sql(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='segments' AND column_name='segment_id'"
    ).fetchone()
    return row is not None


def _recreate_indexes() -> str:
    return """
    CREATE INDEX IF NOT EXISTS segments_video_id_idx ON segments(video_id);
    CREATE INDEX IF NOT EXISTS segments_fts_idx ON segments USING GIN(fts);
    CREATE INDEX IF NOT EXISTS segments_subject_idx ON segments(subject);
    CREATE INDEX IF NOT EXISTS segments_grade_idx ON segments(grade_level);
    CREATE INDEX IF NOT EXISTS segments_embedding_hnsw ON segments
        USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
    """


def upgrade() -> None:
    bind = op.get_bind()
    if _already_migrated(bind):
        return

    bind.exec_driver_sql("ALTER TABLE segments RENAME TO segments_old")
    bind.exec_driver_sql(f"CREATE TABLE segments ({_NEW_COLUMNS})")
    bind.exec_driver_sql(f"""
        INSERT INTO segments (segment_id, {_COPY_COLUMNS})
        SELECT id, {_COPY_COLUMNS}
        FROM segments_old
    """)
    bind.exec_driver_sql("DROP TABLE segments_old")
    bind.exec_driver_sql(_recreate_indexes())


def downgrade() -> None:
    bind = op.get_bind()
    row = bind.exec_driver_sql(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name='segments' AND column_name='id'"
    ).fetchone()
    if row is not None:
        return  # already on the pre-0003 shape

    bind.exec_driver_sql("ALTER TABLE segments RENAME TO segments_new")
    bind.exec_driver_sql(f"CREATE TABLE segments ({_OLD_COLUMNS})")
    bind.exec_driver_sql(f"""
        INSERT INTO segments (id, {_COPY_COLUMNS}, hallucination)
        SELECT segment_id, {_COPY_COLUMNS}, NULL
        FROM segments_new
    """)
    bind.exec_driver_sql("DROP TABLE segments_new")
    bind.exec_driver_sql("""
        CREATE INDEX IF NOT EXISTS segments_video_id_idx ON segments(video_id);
        CREATE INDEX IF NOT EXISTS segments_video_seg_idx ON segments(video_id, seg_index);
        CREATE INDEX IF NOT EXISTS segments_fts_idx ON segments USING GIN(fts);
        CREATE INDEX IF NOT EXISTS segments_subject_idx ON segments(subject);
        CREATE INDEX IF NOT EXISTS segments_grade_idx ON segments(grade_level);
        CREATE INDEX IF NOT EXISTS segments_embedding_hnsw ON segments
            USING hnsw (embedding vector_cosine_ops) WITH (m = 16, ef_construction = 64);
    """)
