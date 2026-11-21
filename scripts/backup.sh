#!/usr/bin/env bash
# Timestamped backup: pg_dump custom format + zstd artefact archive + SHA256SUMS (T-128, docs/29 §7).
#
# Usage: scripts/backup.sh [--out DIR]
#   BACKUP_DIR          destination root (default: backups); --out wins
#   BACKUP_RETENTION    how many backup-* directories to keep (default: 7)
#   ARTIFACT_ROOT       artefact tree to archive (default: data/artifacts)
#   DATABASE_URL        libpq/SQLAlchemy URL. When unset, dump via
#                       `docker compose exec` of COMPOSE_DB_SERVICE (default: postgres;
#                       this repo's service name — the task text's "db" is that service).
# Prints the created directory path on stdout.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

OUT_ROOT="${BACKUP_DIR:-backups}"
RETENTION="${BACKUP_RETENTION:-7}"
ARTIFACT_ROOT="${ARTIFACT_ROOT:-data/artifacts}"
COMPOSE_FILE="${COMPOSE_FILE:-docker/compose.yaml}"
COMPOSE_DB_SERVICE="${COMPOSE_DB_SERVICE:-postgres}"
DB_USER="${ROBOPROBE_DB_USER:-roboprobe}"
DB_NAME="${ROBOPROBE_DB_NAME:-roboprobe}"

while [[ $# -gt 0 ]]; do
    case "$1" in
        --out)
            OUT_ROOT="$2"
            shift 2
            ;;
        *)
            echo "unknown argument: $1" >&2
            exit 2
            ;;
    esac
done

if ! [[ "$RETENTION" =~ ^[0-9]+$ ]] || [[ "$RETENTION" -lt 1 ]]; then
    echo "BACKUP_RETENTION must be a positive integer" >&2
    exit 2
fi

stamp="$(date -u +%Y%m%dT%H%M%S)"
dest="${OUT_ROOT}/backup-${stamp}"
if [[ -e "$dest" ]]; then
    dest="${dest}-$$"
fi
mkdir -p "$dest"

libpq_url() {
    local url="$1"
    url="${url/postgresql+psycopg:\/\//postgresql://}"
    url="${url/postgresql+psycopg2:\/\//postgresql://}"
    printf '%s' "$url"
}

if [[ -n "${DATABASE_URL:-}" ]]; then
    pg_dump -Fc --no-owner --dbname="$(libpq_url "$DATABASE_URL")" -f "$dest/db.dump"
else
    compose=(docker compose -f "$COMPOSE_FILE")
    if [[ -f .env ]]; then
        compose+=(--env-file .env)
    fi
    "${compose[@]}" exec -T "$COMPOSE_DB_SERVICE" \
        pg_dump -Fc --no-owner -U "$DB_USER" -d "$DB_NAME" >"$dest/db.dump"
fi

artifact_parent="$(cd "$(dirname "$ARTIFACT_ROOT")" && pwd)"
artifact_name="$(basename "$ARTIFACT_ROOT")"
mkdir -p "${artifact_parent}/${artifact_name}"
tar -C "$artifact_parent" -cf - "$artifact_name" | zstd -q -o "$dest/artifacts.tar.zst"

(
    cd "$dest"
    sha256sum db.dump artifacts.tar.zst >SHA256SUMS
)

mapfile -t existing < <(find "$OUT_ROOT" -mindepth 1 -maxdepth 1 -type d -name 'backup-*' | sort)
extra=$((${#existing[@]} - RETENTION))
if ((extra > 0)); then
    for ((i = 0; i < extra; i++)); do
        rm -rf "${existing[$i]}"
    done
fi

printf '%s\n' "$dest"
