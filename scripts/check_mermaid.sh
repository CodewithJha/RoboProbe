#!/usr/bin/env bash
# Render every fenced ```mermaid block in the repository's Markdown with mermaid-cli (mmdc).
# Any block that fails to parse or render fails the check.
#
# Usage: scripts/check_mermaid.sh [file.md ...]   (default: every tracked *.md containing a mermaid block)
# Env:
#   MERMAID_CLI_VERSION        npm version of @mermaid-js/mermaid-cli used via npx (default below)
#   MMDC                       explicit mmdc command; overrides npx
#   PUPPETEER_EXECUTABLE_PATH  Chrome/Chromium binary to use instead of puppeteer's bundled download
set -euo pipefail

MERMAID_CLI_VERSION="${MERMAID_CLI_VERSION:-11.12.0}"
ROOT="$(git rev-parse --show-toplevel)"
cd "$ROOT"

if [[ -n "${MMDC:-}" ]]; then
  read -r -a mmdc_cmd <<<"$MMDC"
else
  mmdc_cmd=(npx --yes "@mermaid-js/mermaid-cli@${MERMAID_CLI_VERSION}")
fi

if (($# > 0)); then
  files=("$@")
else
  mapfile -t files < <(git ls-files -z -- '*.md' | xargs -0 -r grep -l '^[[:space:]]*```mermaid' || true)
fi

if ((${#files[@]} == 0)); then
  echo "mermaid: no Mermaid blocks found"
  exit 0
fi

workdir="$(mktemp -d)"
trap 'rm -rf "$workdir"' EXIT

# CI runners and containers run as root without a user namespace sandbox.
printf '{"args":["--no-sandbox","--disable-setuid-sandbox"]}\n' >"$workdir/puppeteer.json"

failed=0
blocks=0
for file in "${files[@]}"; do
  out="$workdir/$(echo "$file" | tr '/' '_')"
  # Markdown mode: mmdc renders each mermaid fence to an SVG and fails on the first invalid one.
  if log="$("${mmdc_cmd[@]}" --quiet -p "$workdir/puppeteer.json" -i "$file" -o "$out" 2>&1)"; then
    n="$(grep -c '^[[:space:]]*```mermaid' "$file" || true)"
    blocks=$((blocks + n))
  else
    echo "::error file=$file::Mermaid render failed"
    echo "$log" >&2
    failed=$((failed + 1))
  fi
done

if ((failed > 0)); then
  echo "mermaid: $failed file(s) with invalid diagrams" >&2
  exit 1
fi
echo "mermaid: rendered $blocks block(s) in ${#files[@]} file(s)"
