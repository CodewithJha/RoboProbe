#!/bin/sh
# Render Prometheus config, injecting API bearer auth only when the token secret is non-empty.
set -eu
src=${PROMETHEUS_CONFIG_SRC:-/etc/prometheus/prometheus.yml}
dst=${TMPDIR:-/tmp}/roboprobe-prometheus.yml
token=${API_TOKEN_FILE:-/run/secrets/api_token}
if [ -s "$token" ]; then
  awk '
    /^[[:space:]]*# api-auth-slot$/ {
      print "    authorization:"
      print "      credentials_file: /run/secrets/api_token"
      next
    }
    { print }
  ' "$src" >"$dst"
else
  grep -v 'api-auth-slot' "$src" >"$dst"
fi
exec prometheus \
  --config.file="$dst" \
  --storage.tsdb.path=/prometheus \
  --web.listen-address=:9090
