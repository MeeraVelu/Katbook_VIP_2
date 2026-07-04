"""Alembic environment. Resolves the DB URL from $DATABASE_URL (normalized to the
psycopg v3 driver) so no credential is ever written to alembic.ini."""

from __future__ import annotations

import os
from logging.config import fileConfig

from alembic import context
from sqlalchemy import engine_from_config, pool

# Reuse the pipeline's URL normalizer so `postgres://` / `postgresql://` from a
# managed provider become `postgresql+psycopg://`.
from pipeline.storage import normalize_db_url

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

_url = normalize_db_url(os.environ.get("DATABASE_URL"))
if _url:
    config.set_main_option("sqlalchemy.url", _url)

# Migrations are hand-written (explicit DDL for vector / tsvector / generated
# columns), so there is no autogenerate target metadata.
target_metadata = None


def run_migrations_offline() -> None:
    context.configure(
        url=config.get_main_option("sqlalchemy.url"),
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
    )
    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    connectable = engine_from_config(
        config.get_section(config.config_ini_section, {}),
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )
    with connectable.connect() as connection:
        context.configure(connection=connection, target_metadata=target_metadata)
        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
