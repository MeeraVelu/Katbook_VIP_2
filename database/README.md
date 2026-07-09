# database/ — database domain

Two things live here, with distinct jobs:

- **`schema.sql`** — a human-readable REFERENCE of the complete, final-state
  schema (videos, jobs, segments — every primary key a UUID). It documents
  what the database looks like; it is not what actually builds it in
  production. Update it whenever a new migration changes the end state, so
  it stays trustworthy.
- **`versions/`** — the real, versioned Alembic migrations. `alembic upgrade
  head` is THE production migration path. Every migration here is written to
  be idempotent (`ADD COLUMN IF NOT EXISTS`, guarded `DO $$` blocks, ...), so
  running it again against an already-migrated database is a safe no-op.

## Production / any real environment

```
alembic upgrade head
```

Run this once per environment (locally, in CI, against a fresh Supabase/cloud
Postgres, or — via the compose `migrate` one-shot — against the bundled
`--profile infra` Postgres). `DATABASE_URL` must be set (`database/env.py`
reads it directly from the environment; nothing is hardcoded in
`alembic.ini`).

```
docker compose exec api alembic upgrade head   # from inside a running container
```

To add a schema change: write a new `database/versions/NNNN_description.py`
(idempotent, following the pattern in `0002_enrich_schema.py`), then update
`schema.sql` to reflect the new end state.

## Fresh dev/test bootstrap only

For a quick throwaway database (no migration history needed — e.g. a local
scratch DB or a CI job that just wants tables to exist):

```
psql "$DATABASE_URL" -f database/schema.sql
```

This is NOT a substitute for `alembic upgrade head` against a real
environment — it doesn't record migration state, so a database bootstrapped
this way and later pointed at `alembic upgrade head` will just no-op (every
statement in both is guarded), but it also won't track which migrations
"applied." Use it only when you don't care about migration history.

## Integration tests

`tests/test_storage_idempotency.py` wipes the `public` schema and runs
`alembic upgrade head` programmatically before each run — it exercises the
same path production uses.
