#!/usr/bin/env bash
# Exercise the production web/API images with disposable storage and generated credentials.
set -euo pipefail

cd "$(dirname "${BASH_SOURCE[0]}")/.."
scratch="$(mktemp -d)"
project="roboprobe-web-smoke-$$"
compose=(docker compose -p "$project" -f docker/compose.yaml -f "$scratch/compose.yaml" --profile app)

cleanup() {
    local result=$?
    if (( result != 0 )); then
        "${compose[@]}" ps -a >&2 || true
        "${compose[@]}" logs --tail 50 2>&1 | python3 -c '
from pathlib import Path
import sys

log = sys.stdin.read()
token = Path(sys.argv[1])
print(log.replace(token.read_text(), "[redacted]") if token.is_file() else log, end="")
' "$scratch/api_token" >&2 || true
    fi
    "${compose[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
    rm -rf "$scratch"
}
trap cleanup EXIT

python3 - "$scratch" <<'PY'
import secrets
import sys
from pathlib import Path

for name in ("db_password", "api_token"):
    path = Path(sys.argv[1]) / name
    path.write_text(secrets.token_urlsafe(32), encoding="utf-8")
    path.chmod(0o644)  # The project directory is private and container users read the files.
PY
export ROBOPROBE_API_TOKEN_FILE="$scratch/api_token"
export ROBOPROBE_WEB_DEFAULT_THEME=dark
export ROBOPROBE_WEB_FEATURES=trials,reports

cat >"$scratch/compose.yaml" <<EOF
services:
  migrate: &artifact_mount
    volumes:
      - smoke-artifacts:/data/artifacts
  api:
    <<: *artifact_mount
    environment:
      ROBOPROBE_API__SSE__PING_INTERVAL_S: "1"
  orchestrator: *artifact_mount
  worker-k2d: *artifact_mount
  web:
    ports: !override
      - "127.0.0.1::8080"
secrets:
  db_password:
    file: "$scratch/db_password"
volumes:
  smoke-artifacts: {}
EOF

if [[ ${WEB_SMOKE_BUILD:-1} == 1 ]]; then
    "${compose[@]}" build api web
fi
startup_started=$SECONDS
"${compose[@]}" up -d --no-build --wait --wait-timeout 180
printf 'Compose ready with migrations applied after %s seconds.\n' "$((SECONDS - startup_started))"
base="http://$("${compose[@]}" port web 8080)"
web_id="$("${compose[@]}" ps -q web)"
[[ "$(docker inspect --format '{{ .HostConfig.ReadonlyRootfs }}' "$web_id")" == true ]]
[[ "$("${compose[@]}" exec -T web id -u)" == 101 ]]

check_security_headers() {
    local headers=$1
    grep -Eiq "^Content-Security-Policy:.*default-src 'self'.*object-src 'none'.*frame-ancestors 'none'" "$headers"
    grep -Eiq '^X-Content-Type-Options: nosniff' "$headers"
    grep -Eiq '^Referrer-Policy: no-referrer' "$headers"
    grep -Eiq '^Permissions-Policy: .*camera=\(\)' "$headers"
}

curl --fail --silent --show-error -D "$scratch/headers" "$base/" -o "$scratch/index.html"
check_security_headers "$scratch/headers"
grep -Eiq '^Cache-Control: no-cache' "$scratch/headers"

curl --fail --silent --show-error -D "$scratch/headers" "$base/campaigns/new" -o "$scratch/fallback.html"
check_security_headers "$scratch/headers"
cmp "$scratch/index.html" "$scratch/fallback.html"

curl --fail --silent --show-error -D "$scratch/headers" "$base/config.json" -o "$scratch/config.json"
check_security_headers "$scratch/headers"
grep -Eiq '^Cache-Control: no-cache' "$scratch/headers"
python3 - "$scratch/config.json" <<'PY'
import json
import sys
from pathlib import Path

config = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
assert config["apiBaseUrl"] == "/api/v1"
assert config["sseUrl"] == "/api/v1/events"
assert config["defaultTheme"] == "dark"
assert config["featureFlags"] == {"trials": True, "reports": True}
PY

asset="$(sed -nE 's/.*src="(\/assets\/[^"]+\.js)".*/\1/p' "$scratch/index.html" | head -n 1)"
[[ -n "$asset" ]]
curl --fail --silent --show-error -I -H 'Accept-Encoding: gzip' "$base$asset" -o "$scratch/headers"
check_security_headers "$scratch/headers"
grep -Eiq '^Cache-Control: public, max-age=31536000, immutable' "$scratch/headers"
grep -Eiq '^Content-Encoding: gzip' "$scratch/headers"

[[ "$(curl --silent --show-error -o /dev/null -w '%{http_code}' "$base/api/v1/campaigns")" == 401 ]]
{ printf 'Authorization: Bearer '; cat "$scratch/api_token"; } >"$scratch/authorization"
curl --fail --silent --show-error --header "@$scratch/authorization" "$base/api/v1/campaigns" >/dev/null

# A healthy SSE stream stays open after delivering its ping. Bound the client and inspect the frame.
sse_exit=0
curl --fail --silent --no-buffer --max-time 5 --header "@$scratch/authorization" \
    -D "$scratch/sse.headers" "$base/api/v1/events" -o "$scratch/events" || sse_exit=$?
[[ "$sse_exit" == 28 ]]
check_security_headers "$scratch/sse.headers"
grep -Eiq '^Content-Type: text/event-stream' "$scratch/sse.headers"
grep -Eiq '^X-Accel-Buffering: no' "$scratch/sse.headers"
grep -q '^: ping' "$scratch/events"

WEB_SMOKE_URL="$base" WEB_SMOKE_TOKEN_FILE="$scratch/api_token" node web/scripts/check-production-csp.mjs

if [[ ${WEB_SMOKE_DEMO:-0} == 1 ]]; then
    COMPOSE_PROJECT_NAME="$project" PROFILES=app scripts/demo.sh |
        while IFS= read -r line; do
            printf '%s\n' "$line"
            printf '%s\t%s\n' "$SECONDS" "$line" >> "$scratch/demo.log"
        done
    campaign_id="$(python3 - "$scratch/demo.log" <<'PYTHON'
import json
import re
import sys
from pathlib import Path

campaign_id = None
first_failure_s = None
final = None
for row in Path(sys.argv[1]).read_text(encoding="utf-8").splitlines():
    elapsed, line = row.split("\t", 1)
    match = re.fullmatch(r"demo campaign ([a-f0-9-]{36})", line)
    if match:
        campaign_id = match[1]
        print(f"First campaign created {elapsed} seconds after smoke start.", file=sys.stderr)
        continue
    if not line.startswith("{"):
        continue
    state = json.loads(line)
    if state.get("campaign_id") != campaign_id or "fail" not in state:
        continue
    final = state
    if first_failure_s is None and state["fail"]:
        first_failure_s = elapsed
assert campaign_id is not None and first_failure_s is not None, "missing campaign or failure"
assert final is not None and final["status"] == "COMPLETED" and final["done"] == final["budget"], final
print(f"First failure observed after {first_failure_s} seconds. Demo completed {final['done']} runs.", file=sys.stderr)
print(campaign_id)
PYTHON
)"
    # The Compose orchestrator finishes simulation separately from on-demand analysis.
    "${compose[@]}" exec -T orchestrator roboprobe --json analyze "$campaign_id" --wait
    worker_count="$("${compose[@]}" ps -q worker-k2d | wc -l | tr -d '[:space:]')"
    WEB_SMOKE_URL="$base" WEB_SMOKE_TOKEN_FILE="$scratch/api_token" \
        WEB_SMOKE_CAMPAIGN_ID="$campaign_id" WEB_SMOKE_WORKER_COUNT="$worker_count" \
        node web/scripts/check-published-quickstart.mjs
fi

# EventSource sends its bearer in the query. Even an upstream outage must keep it out of logs.
"${compose[@]}" stop --timeout 1 api
status="$(curl --silent --show-error --max-time 5 --get --data-urlencode "token@$scratch/api_token" \
    -o /dev/null -w '%{http_code}' "$base/api/v1/events")"
[[ "$status" == 502 || "$status" == 504 ]]
"${compose[@]}" logs web api >"$scratch/proxy.log" 2>&1
if grep -Fq -f "$scratch/api_token" "$scratch/proxy.log"; then
    echo 'The event stream credential appeared in the proxy or API logs.' >&2
    exit 1
fi
echo 'Production web smoke passed (read-only, runtime config, security headers, gzip, SPA and real SSE).'
