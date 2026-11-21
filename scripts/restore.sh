#!/usr/bin/env bash
# Restore a backup created by scripts/backup.sh (T-128, docs/29 §7).
#
# Usage: scripts/restore.sh [--force] BACKUP_DIR
#   Refuses a database that already has rows outside alembic_version unless --force.
#   Then pg_restore --clean --if-exists --no-owner, extracts artefacts, and runs
#   `roboprobe db upgrade` plus `roboprobe artifacts verify`.
#   DATABASE_URL, ARTIFACT_ROOT, COMPOSE_DB_SERVICE: see scripts/backup.sh.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

FORCE=0
BACKUP=""
COMPOSE_FILE="${COMPOSE_FILE:-docker/compose.yaml}"
COMPOSE_DB_SERVICE="${COMPOSE_DB_SERVICE:-postgres}"
DB_USER="${ROBOPROBE_DB_USER:-roboprobe}"
DB_NAME="${ROBOPROBE_DB_NAME:-roboprobe}"
ARTIFACT_ROOT="${ARTIFACT_ROOT:-data/artifacts}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --force)
            FORCE=1
            shift
            ;;
        *)
            if [[ -n "$BACKUP" ]]; then
                echo "unexpected argument: $1" >&2
                exit 2
            fi
            BACKUP="$1"
            shift
            ;;
    esac
done

if [[ -z "$BACKUP" || ! -d "$BACKUP" ]]; then
    echo "usage: scripts/restore.sh [--force] BACKUP_DIR" >&2
    exit 2
fi

(
    cd "$BACKUP"
    sha256sum -c SHA256SUMS
)

libpq_url() {
    local url="$1"
    url="${url/postgresql+psycopg:\/\//postgresql://}"
    url="${url/postgresql+psycopg2:\/\//postgresql://}"
    printf '%s' "$url"
}

# Exact row count across public tables, ignoring the migration stamp.
row_count_sql="SELECT COALESCE(SUM(n), 0) FROM (
  SELECT (xpath('//row/c/text()', query_to_xml(
    format('SELECT count(*) AS c FROM %I.%I', schemaname, tablename), false, true, ''
  )))[1]::text::bigint AS n
  FROM pg_tables
  WHERE schemaname = 'public' AND tablename <> 'alembic_version'
) counts"

if [[ -n "${DATABASE_URL:-}" ]]; then
    url="$(libpq_url "$DATABASE_URL")"
    rows="$(psql "$url" -v ON_ERROR_STOP=1 -tAc "$row_count_sql" | tr -d '[:space:]')"
    if [[ "$rows" != "0" && "$FORCE" -ne 1 ]]; then
        echo "target database has ${rows} rows; pass --force to overwrite" >&2
        exit 1
    fi
    pg_restore --clean --if-exists --no-owner --dbname="$url" "$BACKUP/db.dump"
else
    compose=(docker compose -f "$COMPOSE_FILE")
    if [[ -f .env ]]; then
        compose+=(--env-file .env)
    fi
    rows="$("${compose[@]}" exec -T "$COMPOSE_DB_SERVICE" \
        psql -U "$DB_USER" -d "$DB_NAME" -v ON_ERROR_STOP=1 -tAc "$row_count_sql" | tr -d '[:space:]')"
    if [[ "$rows" != "0" && "$FORCE" -ne 1 ]]; then
        echo "target database has ${rows} rows; pass --force to overwrite" >&2
        exit 1
    fi
    cid="$("${compose[@]}" ps -q "$COMPOSE_DB_SERVICE")"
    docker cp "$BACKUP/db.dump" "${cid}:/tmp/roboprobe-restore.dump"
    "${compose[@]}" exec -T "$COMPOSE_DB_SERVICE" \
        pg_restore --clean --if-exists --no-owner -U "$DB_USER" -d "$DB_NAME" /tmp/roboprobe-restore.dump
    "${compose[@]}" exec -T "$COMPOSE_DB_SERVICE" rm -f /tmp/roboprobe-restore.dump
fi

artifact_parent="$(cd "$(dirname "$ARTIFACT_ROOT")" && pwd)"
zstd -q -dc "$BACKUP/artifacts.tar.zst" | tar -C "$artifact_parent" -xf -

if [[ -x "$ROOT/backend/.venv/bin/roboprobe" ]]; then
    roboprobe=("$ROOT/backend/.venv/bin/roboprobe")
else
    roboprobe=(uv run --directory "$ROOT/backend" roboprobe)
fi

export ROBOPROBE_STORAGE__ARTIFACT_ROOT="$ARTIFACT_ROOT"
if [[ -n "${DATABASE_URL:-}" ]]; then
    case "$DATABASE_URL" in
        postgresql+*) export ROBOPROBE_DATABASE__URL="$DATABASE_URL" ;;
        *) export ROBOPROBE_DATABASE__URL="${DATABASE_URL/postgresql:\/\//postgresql+psycopg://}" ;;
    esac
fi

"${roboprobe[@]}" db upgrade
verify="$("${roboprobe[@]}" --json artifacts verify)"
python3 -c 'import json,sys; payload=json.loads(sys.argv[1]); raise SystemExit(0 if payload.get("ok") else 1)' "$verify"
echo "restore ok"
