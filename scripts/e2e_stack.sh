#!/usr/bin/env bash
# Compose-backed stack for Playwright E2E (T-117). Used by web/e2e global setup and e2e.yml.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

ACTION="${1:-}"
COMPOSE_FILE="${COMPOSE_FILE:-docker/compose.yaml}"
E2E_ENV="${E2E_ENV:-docker/e2e.env}"
ARTIFACTS_DIR="${E2E_ARTIFACT_ROOT:-data/artifacts}"
SECRETS_DIR="${SECRETS_DIR:-secrets}"
DB_PASSWORD_FILE="${SECRETS_DIR}/db_password"
LOG_DIR="${E2E_LOG_DIR:-web/e2e-artifacts}"
READY_URL="${E2E_READY_URL:-http://127.0.0.1:8000/api/v1/health/ready}"
WEB_URL="${E2E_BASE_URL:-http://127.0.0.1:8080}"
READY_TIMEOUT_S="${E2E_READY_TIMEOUT_S:-180}"

compose() {
  local -a args=(docker compose -f "$COMPOSE_FILE" --env-file "$E2E_ENV")
  if [[ -f .env ]]; then
    args+=(--env-file .env)
  fi
  args+=(--profile core --profile app --profile dev "$@")
  "${args[@]}"
}

ensure_secret() {
  mkdir -p "$SECRETS_DIR" && chmod 700 "$SECRETS_DIR"
  if [[ ! -s $DB_PASSWORD_FILE ]]; then
    umask 022
    python3 -c 'import secrets; print(secrets.token_urlsafe(32))' >"$DB_PASSWORD_FILE"
  fi
}

wait_http() {
  local url=$1 timeout=$2
  python3 - "$url" "$timeout" <<'PY'
import sys, time, urllib.error, urllib.request

url, limit = sys.argv[1], float(sys.argv[2])
deadline = time.monotonic() + limit
while time.monotonic() < deadline:
    try:
        with urllib.request.urlopen(url, timeout=3) as response:
            if response.status == 200:
                sys.exit(0)
    except urllib.error.HTTPError as exc:
        if exc.code in {503, 502}:
            time.sleep(2)
            continue
        raise
    except OSError:
        time.sleep(2)
raise SystemExit(f"timed out waiting for {url}")
PY
}

seed_database() {
  local db_pass
  db_pass="$(<"$DB_PASSWORD_FILE")"
  local database_url="postgresql+psycopg://roboprobe:${db_pass}@127.0.0.1:5432/roboprobe"
  rm -rf "$ARTIFACTS_DIR"
  mkdir -p "$ARTIFACTS_DIR"
  uv run --directory backend python tests/fixtures/db/load_seed.py \
    --database-url "$database_url" --artifact-root "$ARTIFACTS_DIR"
}

case "$ACTION" in
  up)
    ensure_secret
    mkdir -p "$ARTIFACTS_DIR" "$LOG_DIR"
    compose down --remove-orphans -v || true
    compose build postgres migrate orchestrator worker-k2d api web
    compose up -d postgres postgres-port
    compose up -d migrate
    compose wait migrate
    python3 - <<'PY'
import socket, sys, time

for _ in range(30):
    try:
        with socket.create_connection(("127.0.0.1", 5432), timeout=1):
            sys.exit(0)
    except OSError:
        time.sleep(1)
raise SystemExit("postgres port 5432 not reachable on loopback")
PY
    seed_database
    compose up -d --wait orchestrator worker-k2d api web
    wait_http "$READY_URL" "$READY_TIMEOUT_S"
    wait_http "$WEB_URL/" 60
    ;;
  down)
    mkdir -p "$LOG_DIR"
    compose logs --no-color >"$LOG_DIR/compose.log" 2>&1 || true
    compose down --remove-orphans
    ;;
  *)
    echo "usage: $0 {up|down}" >&2
    exit 2
    ;;
esac