#!/usr/bin/env bash
# backup.sh — dump the Katbook Postgres database to a dated, compressed file.
#
# Usage:
#   DATABASE_URL=postgresql://user:pass@host:5432/katbook ./scripts/backup.sh [OUT_DIR]
#   # or inside the compose stack:
#   docker compose exec -T postgres pg_dump -U "$POSTGRES_USER" "$POSTGRES_DB" | gzip > backup.sql.gz
#
# Restore (see docs/DATABASE.md for the full procedure):
#   gunzip -c katbook_YYYY-MM-DD_HHMMSS.sql.gz | psql "$DATABASE_URL"
set -euo pipefail

OUT_DIR="${1:-./backups}"
mkdir -p "$OUT_DIR"

if [[ -z "${DATABASE_URL:-}" ]]; then
  echo "ERROR: set DATABASE_URL (postgresql://user:pass@host:port/db)" >&2
  exit 1
fi

STAMP="$(date -u +%Y-%m-%d_%H%M%S)"
OUT_FILE="${OUT_DIR}/katbook_${STAMP}.sql.gz"

echo "Dumping database -> ${OUT_FILE}"
# --no-owner / --no-privileges keep the dump portable across roles.
pg_dump --no-owner --no-privileges "$DATABASE_URL" | gzip -9 > "$OUT_FILE"

echo "Done: $(du -h "$OUT_FILE" | cut -f1) ${OUT_FILE}"
echo "Keep backups off-box (object storage). Test a restore periodically."
