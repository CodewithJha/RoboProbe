#!/usr/bin/env bash
# Create (or re-create) the 50-run k2d demo campaign and wait until it finishes.
# Space registration inside `campaign run` is idempotent (T-047). The orchestrator
# and worker-k2d services of the running core stack execute the runs.
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"
COMPOSE_FILE="${COMPOSE_FILE:-docker/compose.yaml}"
DEMO_CONFIG="${DEMO_CONFIG:-/app/configs/campaigns/k2d_demo_50.yaml}"
DEMO_TIMEOUT_S="${DEMO_TIMEOUT_S:-900}"

args=(docker compose -f "$COMPOSE_FILE")
if [[ -f .env ]]; then
    args+=(--env-file .env)
fi
# shellcheck disable=SC2086
for profile in ${PROFILES:-core}; do
    args+=(--profile "$profile")
done

if ! "${args[@]}" ps --status running --services | grep -qx orchestrator; then
    echo "orchestrator is not running; start the stack with 'make up'" >&2
    exit 1
fi

created="$("${args[@]}" exec -T orchestrator --json campaign run "$DEMO_CONFIG")"
campaign_id="$(
    python3 -c 'import json,sys
for line in sys.stdin:
    line=line.strip()
    if line.startswith("{") and "campaign_id" in line:
        print(json.loads(line)["campaign_id"])
        raise SystemExit(0)
raise SystemExit("campaign run did not print campaign_id")' <<<"$created"
)"
echo "demo campaign ${campaign_id}"

if command -v timeout >/dev/null 2>&1; then
    timeout "$DEMO_TIMEOUT_S" "${args[@]}" exec -T orchestrator --json campaign status "$campaign_id" --watch
else
    "${args[@]}" exec -T orchestrator --json campaign status "$campaign_id" --watch
fi
