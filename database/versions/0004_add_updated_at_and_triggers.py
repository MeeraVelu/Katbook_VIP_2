"""add updated_at + triggers — segments gains updated_at, all three tables get
an auto-update trigger

videos and jobs already have updated_at (added in 0001) and it's been
maintained by application code since day one — this migration does NOT
touch or backfill their existing values (overwriting real history with
created_at would destroy it). Only segments is missing the column, so only
segments gets backfilled (updated_at = created_at for pre-existing rows).

All three tables get a BEFORE UPDATE trigger, backed by one shared
set_updated_at() function, so updated_at is correct even for a future
write path that forgets to set it explicitly.

Idempotent: every statement is naturally safe to rerun (ADD COLUMN IF NOT
EXISTS, CREATE OR REPLACE FUNCTION, DROP TRIGGER IF EXISTS + CREATE), and
the backfill only fires the first time a table is missing the column.

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-09
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | Sequence[str] | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

_TABLES = ("segments", "videos", "jobs")

_FUNCTION_SQL = """
CREATE OR REPLACE FUNCTION set_updated_at()
RETURNS TRIGGER AS $$
BEGIN
  NEW.updated_at = now();
  RETURN NEW;
END;
$$ LANGUAGE plpgsql;
"""


def _has_column(bind, table: str, column: str) -> bool:
    row = bind.exec_driver_sql(
        "SELECT 1 FROM information_schema.columns "
        "WHERE table_name=%s AND column_name=%s",
        (table, column),
    ).fetchone()
    return row is not None


def upgrade() -> None:
    bind = op.get_bind()

    for table in _TABLES:
        had_it = _has_column(bind, table, "updated_at")
        bind.exec_driver_sql(
            f"ALTER TABLE {table} ADD COLUMN IF NOT EXISTS updated_at "
            f"TIMESTAMPTZ NOT NULL DEFAULT now()"
        )
        if not had_it:
            # only true for `segments` in practice — videos/jobs already had
            # this column (added in 0001) so `had_it` is True for them and
            # this backfill is skipped, preserving their real history.
            bind.exec_driver_sql(f"UPDATE {table} SET updated_at = created_at")

    bind.exec_driver_sql(_FUNCTION_SQL)

    for table in _TABLES:
        bind.exec_driver_sql(f"DROP TRIGGER IF EXISTS {table}_set_updated_at ON {table}")
        bind.exec_driver_sql(f"""
            CREATE TRIGGER {table}_set_updated_at
                BEFORE UPDATE ON {table}
                FOR EACH ROW EXECUTE FUNCTION set_updated_at();
        """)


def downgrade() -> None:
    bind = op.get_bind()
    for table in _TABLES:
        bind.exec_driver_sql(f"DROP TRIGGER IF EXISTS {table}_set_updated_at ON {table}")
    bind.exec_driver_sql("DROP FUNCTION IF EXISTS set_updated_at()")
    # segments.updated_at was added here; videos/jobs.updated_at predates this
    # migration (added in 0001) and must never be dropped by this downgrade.
    bind.exec_driver_sql("ALTER TABLE segments DROP COLUMN IF EXISTS updated_at")
