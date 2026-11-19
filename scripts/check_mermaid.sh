#!/usr/bin/env bash
# Render every fenced ```mermaid block in the repository's Markdown with mermaid-cli (mmdc).
# Any block that fails to parse or render fails the check. Files are rendered in parallel.
#
# Usage: scripts/check_mermaid.sh [file.md ...]   (default: every tracked *.md containing a mermaid block)
# Env:
#   MERMAID_CLI_VERSION        npm version of @mermaid-js/mermaid-cli used via npx (default below)
#   MMDC                       explicit mmdc command; overrides npx
#   MERMAID_JOBS               parallel renderers (default: number of CPUs)
#   PUPPETEER_EXECUTABLE_PATH  Chrome/Chromium binary to use instead of puppeteer's bundled download
set -euo pipefail

MERMAID_CLI_VERSION="${MERMAID_CLI_VERSION:-11.12.0}"
MERMAID_JOBS="${MERMAID_JOBS:-$(getconf _NPROCESSORS_ONLN 2>/dev/null || echo 1)}"
FENCE='^[[:space:]]*```mermaid'
SELF="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)/$(basename "${BASH_SOURCE[0]}")"

# Worker mode: render one file into $MERMAID_WORKDIR. Invoked by the parallel driver below.
if [[ "${1:-}" == "--render-one" ]]; then
  file="$2"
  if [[ -n "${MMDC:-}" ]]; then
    read -r -a mmdc_cmd <<<"$MMDC"
  else
    mmdc_cmd=(npx --yes "@mermaid-js/mermaid-cli@${MERMAID_CLI_VERSION}")
  fi
  out="$MERMAID_WORKDIR/$(printf '%s' "$file" | tr '/' '_')"
  # Markdown mode: mmdc renders each mermaid fence to an SVG and fails on the first invalid one.
  if ! log="$("${mmdc_cmd[@]}" --quiet -p "$MERMAID_WORKDIR/puppeteer.json" -i "$file" -o "$out" 2>&1)"; then
    printf '::error file=%s::Mermaid render failed\n%s\n' "$file" "$log" >&2
    exit 1
  fi
  exit 0
fi

ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

if (($# > 0)); then
  files=("$@")
else
  mapfile -t files < <(git ls-files -z -- '*.md' | xargs -0 -r grep -l "$FENCE" || true)
fi

if ((${#files[@]} == 0)); then
  echo "mermaid: no Mermaid blocks found"
  exit 0
fi

MERMAID_WORKDIR="$(mktemp -d)"
export MERMAID_WORKDIR MERMAID_CLI_VERSION
trap 'rm -rf "$MERMAID_WORKDIR"' EXIT

# CI runners and containers run as root without a user namespace sandbox.
printf '{"args":["--no-sandbox","--disable-setuid-sandbox"]}\n' >"$MERMAID_WORKDIR/puppeteer.json"

# Warm the npx cache once so parallel workers don't race to install mermaid-cli.
if [[ -z "${MMDC:-}" ]]; then
  npx --yes "@mermaid-js/mermaid-cli@${MERMAID_CLI_VERSION}" --version >/dev/null
fi

blocks="$(cat "${files[@]}" | grep -c "$FENCE" || true)"
if ! printf '%s\0' "${files[@]}" | xargs -0 -n 1 -P "$MERMAID_JOBS" "$SELF" --render-one; then
  echo "mermaid: invalid diagram(s) found (see errors above)" >&2
  exit 1
fi
echo "mermaid: rendered $blocks block(s) in ${#files[@]} file(s) with $MERMAID_JOBS job(s)"
