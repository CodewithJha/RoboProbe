#!/usr/bin/env bash
# SC-6 live-stack scripted sessions (T-108). Host-network backend + bridge web (api via host-gateway).
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$root"

if docker info >/dev/null 2>&1; then
  docker() { command docker "$@"; }
elif sudo docker info >/dev/null 2>&1; then
  docker() { sudo docker "$@"; }
else
  echo "Docker daemon is not reachable." >&2
  exit 1
fi

scratch="$(mktemp -d)"
project="sc6-hallway-$$"
db_port="${SC6_DB_PORT:-55434}"
tag="${ROBOPROBE_IMAGE_TAG:-main}"
printf 'ROBOPROBE_IMAGE_TAG=%s\n' "$tag" >"$scratch/stack.env"

python3 - "$scratch" <<'PY'
import secrets
from pathlib import Path
root = Path(__import__("sys").argv[1])
(root / "db_password").write_text(secrets.token_urlsafe(32), encoding="utf-8")
(root / "api_token").write_text(secrets.token_urlsafe(32), encoding="utf-8")
(root / "artifacts").mkdir(exist_ok=True)
PY
chmod 1777 "$scratch/artifacts"

cat >"$scratch/overlay.yaml" <<EOF
services:
  postgres:
    ports:
      - "127.0.0.1:$db_port:5432"
  migrate:
    network_mode: host
    environment:
      ROBOPROBE_DATABASE__URL: postgresql+psycopg://roboprobe@127.0.0.1:$db_port/roboprobe
  api:
    network_mode: host
    environment:
      ROBOPROBE_DATABASE__URL: postgresql+psycopg://roboprobe@127.0.0.1:$db_port/roboprobe
  orchestrator:
    network_mode: host
    environment:
      ROBOPROBE_DATABASE__URL: postgresql+psycopg://roboprobe@127.0.0.1:$db_port/roboprobe
      ROBOPROBE_STORAGE__ARTIFACT_ROOT: $scratch/artifacts
    volumes:
      - $scratch/artifacts:/data/artifacts
  worker-k2d:
    network_mode: host
    deploy:
      replicas: 1
    environment:
      ROBOPROBE_DATABASE__URL: postgresql+psycopg://roboprobe@127.0.0.1:$db_port/roboprobe
      ROBOPROBE_STORAGE__ARTIFACT_ROOT: $scratch/artifacts
    volumes:
      - $scratch/artifacts:/data/artifacts
  web:
    ports: !override
      - "127.0.0.1::8080"
    extra_hosts:
      - "api:host-gateway"
    depends_on:
      api:
        condition: service_started
secrets:
  db_password:
    file: $scratch/db_password
  api_token:
    file: $scratch/api_token
EOF

compose=(
  docker compose -p "$project"
  --env-file "$scratch/stack.env"
  -f docker/compose.yaml
  -f "$scratch/overlay.yaml"
  --profile app
)

cleanup() {
  "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$scratch"
}
trap cleanup EXIT

export ROBOPROBE_API_TOKEN_FILE="$scratch/api_token"
"${compose[@]}" pull --quiet
"${compose[@]}" up -d --no-build postgres
"${compose[@]}" up -d --no-build --wait migrate
"${compose[@]}" up -d --no-build api orchestrator worker-k2d
sleep 3
"${compose[@]}" exec -T orchestrator roboprobe space register /app/configs/scenario_spaces/warehouse_v1.yaml
"${compose[@]}" up -d --no-build web
for _ in $(seq 1 45); do
  curl -sf "http://127.0.0.1:${ROBOPROBE_WEB_PORT:-8080}/" >/dev/null && break
  sleep 2
done
port="$("${compose[@]}" port web 8080 | awk -F: '{print $NF}')"
base="http://127.0.0.1:${port}"
bearer="$(tr -d '[:space:]' <"$scratch/api_token")"
for _ in $(seq 1 30); do
  curl -sf -H "Authorization: Bearer $bearer" "$base/api/v1/spaces" >/dev/null && break
  sleep 2
done
export WEB_SMOKE_URL="$base"
export WEB_SMOKE_TOKEN_FILE="$scratch/api_token"
export SC6_FAST="${SC6_FAST:-1}"
(cd web && pnpm exec node scripts/sc6_hallway_protocol.mjs)