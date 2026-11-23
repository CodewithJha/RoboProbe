#!/usr/bin/env bash
# Two Compose projects on one VM: machine A (API + TLS DB) and machine B (remote worker, verify-full).
# Postgres listens on loopback only; the worker reaches it via host-gateway (no public DB port).
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
host_project="t129-host-$$"
worker_project="t129-worker-$$"
postgres_host="t129-postgres"
db_loop_port="${T129_DB_PORT:-15432}"
log="$scratch/verify.log"
evidence_append="${1:-}"

cleanup() {
  docker compose -p "$host_project" -f "$scratch/host.compose.yaml" down -v --remove-orphans >/dev/null 2>&1 || true
  docker compose -p "$worker_project" -f docker/compose.worker.yaml -f "$scratch/worker.override.yaml" \
    down --remove-orphans >/dev/null 2>&1 || true
  rm -rf "$scratch"
}
trap cleanup EXIT

openssl req -new -x509 -days 1 -nodes -text -out "$scratch/ca.crt" -keyout "$scratch/ca.key" \
  -subj "/CN=RoboProbe-T129-CA" >/dev/null 2>&1
openssl req -new -nodes -text -out "$scratch/server.csr" -keyout "$scratch/server.key" \
  -subj "/CN=$postgres_host" >/dev/null 2>&1
printf 'subjectAltName=DNS:%s\n' "$postgres_host" >"$scratch/server.ext"
openssl x509 -req -in "$scratch/server.csr" -CA "$scratch/ca.crt" -CAkey "$scratch/ca.key" \
  -CAcreateserial -out "$scratch/server.crt" -days 1 -extfile "$scratch/server.ext" >/dev/null 2>&1
sudo chown 999:999 "$scratch/server.key" "$scratch/server.crt" 2>/dev/null || true
openssl verify -CAfile "$scratch/ca.crt" "$scratch/server.crt" >/dev/null

python3 - "$scratch" <<'PY'
import secrets
from pathlib import Path

root = Path(__import__("sys").argv[1])
(root / "db_password").write_text(secrets.token_urlsafe(24), encoding="utf-8")
(root / "api_token").write_text(secrets.token_urlsafe(24), encoding="utf-8")
(root / "pg_hba.conf").write_text(
    "local all all trust\n"
    "host all all 127.0.0.1/32 scram-sha-256\n"
    "hostssl all all 0.0.0.0/0 scram-sha-256\n",
    encoding="utf-8",
)
PY

mkdir -p "$scratch/artifacts"
chmod 1777 "$scratch/artifacts"

tag="${ROBOPROBE_IMAGE_TAG:-main}"
docker pull -q "ghcr.io/codewithjha/roboprobe-backend:$tag"

cat >"$scratch/host.env" <<EOF
ROBOPROBE_IMAGE_TAG=$tag
EOF

cat >"$scratch/host.compose.yaml" <<EOF
name: $host_project
services:
  postgres:
    image: postgres:17@sha256:b60e90042aa6b8dbecd58e224b3e36114dbf8ad754465264c2476ad58a86e45c
    ports:
      - "127.0.0.1:$db_loop_port:5432"
    environment:
      POSTGRES_DB: roboprobe
      POSTGRES_USER: roboprobe
      POSTGRES_PASSWORD_FILE: /run/secrets/db_password
    secrets: [db_password]
    volumes:
      - pgdata:/var/lib/postgresql/data
      - $scratch/server.crt:/var/lib/postgresql/tls/server.crt:ro
      - $scratch/server.key:/var/lib/postgresql/tls/server.key:ro
      - $scratch/pg_hba.conf:/var/lib/postgresql/tls/pg_hba.conf:ro
    command:
      - postgres
      - -c
      - ssl=on
      - -c
      - ssl_cert_file=/var/lib/postgresql/tls/server.crt
      - -c
      - ssl_key_file=/var/lib/postgresql/tls/server.key
      - -c
      - hba_file=/var/lib/postgresql/tls/pg_hba.conf
    healthcheck:
      test: ["CMD-SHELL", "pg_isready -h 127.0.0.1 -U roboprobe -d roboprobe"]
      interval: 3s
      timeout: 5s
      retries: 20

  migrate:
    image: ghcr.io/codewithjha/roboprobe-backend:$tag
    network_mode: host
    environment:
      ROBOPROBE_DATABASE__URL: postgresql+psycopg://roboprobe@127.0.0.1:$db_loop_port/roboprobe?sslmode=require
    secrets: [db_password]
    command: ["db", "upgrade"]
    depends_on:
      postgres: {condition: service_healthy}

  orchestrator:
    image: ghcr.io/codewithjha/roboprobe-backend:$tag
    network_mode: host
    environment:
      ROBOPROBE_DATABASE__URL: postgresql+psycopg://roboprobe@127.0.0.1:$db_loop_port/roboprobe?sslmode=require
      ROBOPROBE_STORAGE__ARTIFACT_ROOT: $scratch/artifacts
    secrets: [db_password]
    command: ["orchestrator"]
    depends_on:
      migrate: {condition: service_completed_successfully}

secrets:
  db_password:
    file: $scratch/db_password

volumes:
  pgdata: {}
EOF

cat >"$scratch/worker.override.yaml" <<EOF
services:
  worker-k2d:
    network_mode: host
    extra_hosts:
      - "$postgres_host:127.0.0.1"
EOF

{
  echo "=== T-129 two-node verification $(date -u +%Y-%m-%dT%H:%M:%SZ) ==="
  echo "Host project: $host_project; worker project: $worker_project"
  echo "Postgres TLS on 127.0.0.1:$db_loop_port only (machine A)."
  echo "Worker DSN host: $postgres_host -> host-gateway (machine B compose)."
} | tee "$log"

docker compose -p "$host_project" --env-file "$scratch/host.env" -f "$scratch/host.compose.yaml" up -d --wait --wait-timeout 180

cat >"$scratch/worker.env" <<EOF
ROBOPROBE_IMAGE_TAG=$tag
ROBOPROBE_REMOTE_DATABASE_URL=postgresql+psycopg://roboprobe@$postgres_host:$db_loop_port/roboprobe?sslmode=disable
ROBOPROBE_REMOTE_WORKER_ID=t129-cloud-vm
ROBOPROBE_REMOTE_ARTIFACT_ROOT=$scratch/artifacts
ROBOPROBE_REMOTE_CA_FILE=$scratch/ca.crt
ROBOPROBE_REMOTE_PASSWORD_FILE=$scratch/db_password
EOF

worker_net_args=(
  --project-name "$worker_project"
  --env-file "$scratch/worker.env"
  -f docker/compose.worker.yaml
  -f "$scratch/worker.override.yaml"
)
docker compose "${worker_net_args[@]}" --profile kinematic2d pull -q
docker compose "${worker_net_args[@]}" --profile kinematic2d up -d worker-k2d

deadline=$((SECONDS + 120))
registered=0
while (( SECONDS < deadline )); do
  registered="$(docker compose -p "$host_project" -f "$scratch/host.compose.yaml" exec -T postgres \
    psql -U roboprobe -d roboprobe -tAc "SELECT count(*) FROM workers WHERE status='IDLE'")"
  registered="${registered//[[:space:]]/}"
  [[ "$registered" -ge 1 ]] && break
  sleep 2
done

tls_line="$(docker compose "${worker_net_args[@]}" exec -T worker-k2d python -c "
from roboprobe.core.settings import load_settings
s = load_settings()
print(s.database.sslmode, s.database.url.get_secret_value().split('?')[-1])
" 2>/dev/null | tr -d '\r')"

marker="t129-probe-$$"
echo "shared-artifact-ok" >"$scratch/artifacts/$marker"

{
  echo "Idle workers on host DB: $registered"
  echo "Worker typed TLS: $tls_line"
  docker compose "${worker_net_args[@]}" exec -T worker-k2d \
    test -f "/data/artifacts/$marker" && echo "Worker shared artifact mount: yes"
  ss -lnt 2>/dev/null | awk -v p=":$db_loop_port" '$4 ~ p {found=1} END{print found ? "Postgres loopback bind: yes" : "Postgres loopback bind: no"}'
  ss -lnt 2>/dev/null | grep -E '^LISTEN.*:5432' | grep -vq 127.0.0.1 && echo "WARNING: non-loopback 5432" || echo "No public 5432 listener."
} | tee -a "$log"

[[ "$registered" -ge 1 ]] || {
  echo "Worker did not register." | tee -a "$log" >&2
  exit 1
}

if [[ -n "$evidence_append" && "$evidence_append" != "/dev/null" ]]; then
  {
    echo ""
    echo "## Cloud VM two-node run ($(TZ=Asia/Kolkata date '+%Y-%m-%d %H:%M:%S %Z'))"
    echo ""
    echo "Machine A: \`$host_project\` (Postgres TLS + orchestrator). Machine B: \`$worker_project\`"
    echo "(\`compose.worker.yaml\`, \`verify-full\`, shared artifact bind). Database reachable on"
    echo "loopback port $db_loop_port only; worker uses \`host-gateway\` DNS \`$postgres_host\`."
    echo ""
    sed 's/^/    /' "$log"
  } >>"$evidence_append"
fi

cat "$log"