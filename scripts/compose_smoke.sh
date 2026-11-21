#!/usr/bin/env bash
# Core-profile compose smoke for T-047 (later reused by the e2e workflow).
# Checks orchestrator and worker-k2d, their /healthz probes, and the replica knob.
# When the Docker daemon answers, also renders `docker compose config`.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
COMPOSE_FILE="${COMPOSE_FILE:-docker/compose.yaml}"

python3 - "$COMPOSE_FILE" <<'PY'
import sys
from pathlib import Path

import yaml

path = Path(sys.argv[1])
document = yaml.safe_load(path.read_text(encoding="utf-8"))
services = document.get("services") or {}
for name in ("orchestrator", "worker-k2d"):
    service = services.get(name)
    if not isinstance(service, dict):
        raise SystemExit(f"missing service {name} in {path}")
    probe = str((service.get("healthcheck") or {}).get("test", ""))
    if "healthz" not in probe:
        raise SystemExit(f"{name} healthcheck must request /healthz")
worker = services["worker-k2d"]
replicas = str((worker.get("deploy") or {}).get("replicas", ""))
if "ROBOPROBE_K2D_REPLICAS" not in replicas:
    raise SystemExit("worker-k2d replicas must come from ROBOPROBE_K2D_REPLICAS")
command = worker.get("command")
if command != ["worker", "--backend", "kinematic2d"]:
    raise SystemExit(f"unexpected worker-k2d command: {command!r}")
print("compose file ok")
PY

if command -v docker >/dev/null 2>&1 && docker info >/dev/null 2>&1; then
    args=(docker compose -f "$COMPOSE_FILE")
    if [[ -f .env ]]; then
        args+=(--env-file .env)
    fi
    # shellcheck disable=SC2086
    for profile in ${PROFILES:-core}; do
        args+=(--profile "$profile")
    done
    rendered="$("${args[@]}" config)"
    python3 -c 'import sys,yaml; d=yaml.safe_load(sys.stdin.read()); s=d["services"]; assert "orchestrator" in s and "worker-k2d" in s; assert "healthz" in str(s["orchestrator"].get("healthcheck"))' <<<"$rendered"
    echo "docker compose config ok"
else
    echo "docker daemon unavailable; skipped docker compose config" >&2
fi
