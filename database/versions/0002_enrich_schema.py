"""enrich schema — video_filename, profile, error_stage, objects, learning_objectives

Adds the columns from the combined current + teammate schema review:
  videos:   video_filename, profile, tagging_path CHECK
  jobs:     video_filename, error_stage, progress_pct NOT NULL DEFAULT 0,
            state CHECK gains 'dead_letter'
  segments: objects, learning_obj renamed to learning_objectives, fts
            regenerated to also index ocr

All new columns are nullable or defaulted, so existing rows and existing
pipeline code keep working unchanged — every statement is guarded
(ADD COLUMN IF NOT EXISTS / conditional rename / conditional constraint
replace), so this migration is safe to run more than once.

Note on CHECK constraints: videos.status intentionally does NOT gain a
'duplicate' value (exact-duplicate videos are stored as status='done',
is_duplicate=TRUE — nothing ever writes status='duplicate'), and
segments.difficulty / segments.content_type intentionally do NOT get CHECK
constraints — they're free text produced by the tagging LLM, which is not
guaranteed to conform to the prompted taxonomy; a violated CHECK would fail
that segment's INSERT and roll back the whole video's storage transaction
(pipeline/storage.py stores a video + all its segments in one transaction).

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-08
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | Sequence[str] | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_UPGRADE_SQL = """
-- ---- videos ----------------------------------------------------------
ALTER TABLE videos ADD COLUMN IF NOT EXISTS video_filename TEXT;
ALTER TABLE videos ADD COLUMN IF NOT EXISTS profile        TEXT;

DO $$ BEGIN
    ALTER TABLE videos ADD CONSTRAINT videos_tagging_path_check
        CHECK (tagging_path IS NULL OR tagging_path IN ('voice','silent'));
EXCEPTION WHEN duplicate_object THEN NULL; END $$;

-- ---- jobs --------------------------------------------------------------
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS video_filename TEXT;
ALTER TABLE jobs ADD COLUMN IF NOT EXISTS error_stage    TEXT;

UPDATE jobs SET progress_pct = 0 WHERE progress_pct IS NULL;
ALTER TABLE jobs ALTER COLUMN progress_pct SET DEFAULT 0;
ALTER TABLE jobs ALTER COLUMN progress_pct SET NOT NULL;

ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_state_check;
ALTER TABLE jobs ADD CONSTRAINT jobs_state_check
    CHECK (state IN ('queued','processing','done','failed','dead_letter'));

-- ---- segments ------------------------------------------------------------
ALTER TABLE segments ADD COLUMN IF NOT EXISTS objects JSONB NOT NULL DEFAULT '[]'::jsonb;

DO $$ BEGIN
    IF EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='segments' AND column_name='learning_obj'
    ) AND NOT EXISTS (
        SELECT 1 FROM information_schema.columns
        WHERE table_name='segments' AND column_name='learning_objectives'
    ) THEN
        ALTER TABLE segments RENAME COLUMN learning_obj TO learning_objectives;
    END IF;
END $$;
ALTER TABLE segments ADD COLUMN IF NOT EXISTS learning_objectives JSONB NOT NULL DEFAULT '[]'::jsonb;

-- fts: regenerate only if 'ocr' isn't already part of the generated
-- expression, so re-running this migration doesn't rebuild the column (and
-- its GIN index) on every apply.
DO $$
DECLARE cur_def text;
BEGIN
    SELECT pg_get_expr(a.adbin, a.adrelid) INTO cur_def
    FROM pg_attrdef a
    JOIN pg_attribute c ON c.attrelid = a.adrelid AND c.attnum = a.adnum
    WHERE a.adrelid = 'segments'::regclass AND c.attname = 'fts';

    IF cur_def IS NULL OR cur_def NOT LIKE '%%ocr%%' THEN
        ALTER TABLE segments DROP COLUMN IF EXISTS fts;
        ALTER TABLE segments ADD COLUMN fts tsvector GENERATED ALWAYS AS (
            to_tsvector('simple',
                coalesce(transcript_text,'') || ' ' ||
                coalesce(summary,'') || ' ' ||
                coalesce(topic,'') || ' ' ||
                coalesce(ocr,''))
        ) STORED;
        CREATE INDEX IF NOT EXISTS segments_fts_idx ON segments USING GIN(fts);
    END IF;
END $$;
"""


def upgrade() -> None:
    op.get_bind().exec_driver_sql(_UPGRADE_SQL)


def downgrade() -> None:
    bind = op.get_bind()
    bind.exec_driver_sql("ALTER TABLE videos DROP COLUMN IF EXISTS video_filename")
    bind.exec_driver_sql("ALTER TABLE videos DROP COLUMN IF EXISTS profile")
    bind.exec_driver_sql("ALTER TABLE videos DROP CONSTRAINT IF EXISTS videos_tagging_path_check")
    bind.exec_driver_sql("ALTER TABLE jobs DROP COLUMN IF EXISTS video_filename")
    bind.exec_driver_sql("ALTER TABLE jobs DROP COLUMN IF EXISTS error_stage")
    bind.exec_driver_sql("ALTER TABLE jobs ALTER COLUMN progress_pct DROP NOT NULL")
    bind.exec_driver_sql("ALTER TABLE jobs ALTER COLUMN progress_pct DROP DEFAULT")
    bind.exec_driver_sql("ALTER TABLE jobs DROP CONSTRAINT IF EXISTS jobs_state_check")
    bind.exec_driver_sql(
        "ALTER TABLE jobs ADD CONSTRAINT jobs_state_check "
        "CHECK (state IN ('queued','processing','done','failed'))"
    )
    bind.exec_driver_sql("ALTER TABLE segments DROP COLUMN IF EXISTS objects")
    bind.exec_driver_sql(
        "DO $$ BEGIN "
        "IF EXISTS (SELECT 1 FROM information_schema.columns WHERE table_name='segments' "
        "AND column_name='learning_objectives') AND NOT EXISTS "
        "(SELECT 1 FROM information_schema.columns WHERE table_name='segments' "
        "AND column_name='learning_obj') THEN "
        "ALTER TABLE segments RENAME COLUMN learning_objectives TO learning_obj; "
        "END IF; END $$;"
    )
