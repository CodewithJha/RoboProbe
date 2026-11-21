#!/usr/bin/env bash
# Round-trip backup/restore against a local Postgres (T-128).
# Requires psql, pg_dump, pg_restore, zstd, and a superuser role that can create a database.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)"
BASE_URL="${BACKUP_TEST_URL:-postgresql://roboprobe@127.0.0.1:5432/postgres}"
DB_NAME="roboprobe_backup_it"

psql "$BASE_URL" -v ON_ERROR_STOP=1 -c "SELECT 1" >/dev/null
psql "$BASE_URL" -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS ${DB_NAME}"
psql "$BASE_URL" -v ON_ERROR_STOP=1 -c "CREATE DATABASE ${DB_NAME}"

plain="${BASE_URL%/*}/${DB_NAME}"
sqlalchemy="${plain/postgresql:\/\//postgresql+psycopg://}"
work="$(mktemp -d)"
trap 'rm -rf "$work"; psql "$BASE_URL" -v ON_ERROR_STOP=1 -c "DROP DATABASE IF EXISTS ${DB_NAME}" >/dev/null' EXIT

artifacts="${work}/artifacts"
export ARTIFACT_ROOT="$artifacts"
export DATABASE_URL="$plain"
export ROBOPROBE_DATABASE__URL="$sqlalchemy"
export ROBOPROBE_STORAGE__ARTIFACT_ROOT="$artifacts"
unset ROBOPROBE_DATABASE__PASSWORD_FILE || true

mkdir -p "$artifacts"
python3 - "$artifacts" <<'PY'
import hashlib
import pathlib
import sys

root = pathlib.Path(sys.argv[1])
data = b"roboprobe-backup-blob\n"
digest = hashlib.sha256(data).hexdigest()
path = root / "sha256" / digest[:2] / digest[2:4] / f"{digest}.bin"
path.parent.mkdir(parents=True, exist_ok=True)
path.write_bytes(data)
PY

roboprobe=("$ROOT/backend/.venv/bin/roboprobe")
if [[ ! -x "${roboprobe[0]}" ]]; then
    roboprobe=(uv run --directory "$ROOT/backend" roboprobe)
fi
"${roboprobe[@]}" db upgrade
psql "$plain" -v ON_ERROR_STOP=1 -c \
    "INSERT INTO events (topic, payload) VALUES ('alert', '{\"level\":\"info\",\"message\":\"kept\"}');"

backup_root="${work}/backups"
first="$(BACKUP_DIR="$backup_root" BACKUP_RETENTION=1 "$ROOT/scripts/backup.sh" --out "$backup_root")"
# Retention keeps the newest directory only.
sleep 1
second="$(BACKUP_DIR="$backup_root" BACKUP_RETENTION=1 "$ROOT/scripts/backup.sh" --out "$backup_root")"
[[ -d "$second" ]]
[[ ! -d "$first" ]]

if "$ROOT/scripts/restore.sh" "$second"; then
    echo "restore without --force should fail on a non-empty database" >&2
    exit 1
fi
still="$(psql "$plain" -tAc "SELECT count(*) FROM events" | tr -d '[:space:]')"
[[ "$still" == "1" ]]

psql "$plain" -v ON_ERROR_STOP=1 -c "DELETE FROM events"
rm -rf "$artifacts"
"$ROOT/scripts/restore.sh" --force "$second"

restored="$(psql "$plain" -tAc "SELECT count(*) FROM events" | tr -d '[:space:]')"
[[ "$restored" == "1" ]]
payload="$(psql "$plain" -tAc "SELECT payload->>'message' FROM events" | tr -d '[:space:]')"
[[ "$payload" == "kept" ]]
find "$artifacts/sha256" -type f | grep -q .
echo "backup restore round-trip ok"
