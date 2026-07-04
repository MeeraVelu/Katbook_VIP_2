# alembic/ — database domain

Database schema migrations (the schema's source of truth). `versions/` holds the
migrations; `env.py` resolves the URL from `$DATABASE_URL`. Apply with
`alembic upgrade head` (the compose `migrate` service runs this before api/worker).
