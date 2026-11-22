#!/bin/sh
# Writes runtime dashboard config (doc 27 §4.12) before nginx starts.
set -eu

dest="${NGINX_CONFIG_JSON_DIR:-/var/lib/nginx/runtime}"
mkdir -p "$dest"

api_base="${ROBOPROBE_WEB_API_BASE_URL:-/api/v1}"
sse_url="${ROBOPROBE_WEB_SSE_URL:-/api/v1/events}"
theme="${ROBOPROBE_WEB_DEFAULT_THEME:-system}"
features="${ROBOPROBE_WEB_FEATURES:-trials,reports}"

trials=false
reports=false
old_ifs=$IFS
IFS=','
for flag in $features; do
  case "$(printf '%s' "$flag" | tr -d ' ')" in
    trials) trials=true ;;
    reports) reports=true ;;
  esac
done
IFS=$old_ifs

printf '%s\n' \
  "{\"apiBaseUrl\":\"${api_base}\",\"sseUrl\":\"${sse_url}\",\"defaultTheme\":\"${theme}\",\"featureFlags\":{\"trials\":${trials},\"reports\":${reports}}}" \
  >"${dest}/config.json"