#!/usr/bin/env bash
# Documentation quality gate (doc 20 §1, `docs.yml`; `make docs-check`).
# Runs every check and reports all failures before exiting non-zero:
#   markdownlint  - Markdown style/structure (.markdownlint.jsonc, .markdownlint-cli2.jsonc)
#   mermaid       - every ```mermaid block renders (scripts/check_mermaid.sh)
#   links         - relative links and #anchors resolve; external URLs too when LINKS_ONLINE=1 (lychee.toml)
#   adr-index     - ADR indexes match docs/adr/ (scripts/check_adr_index.py + its unit tests)
#
# Usage: scripts/check_docs.sh [check ...]      (default: all checks, in the order above)
# Env:
#   MARKDOWNLINT_CLI2_VERSION  npm version of markdownlint-cli2 run via npx (default below)
#   LYCHEE                     lychee command (default: `lychee` on PATH, else the Docker image below)
#   LYCHEE_IMAGE               container image used when lychee is not installed
#   LINKS_ONLINE               1 = also check external URLs (network, retries per lychee.toml); default 0
#   PYTHON                     Python interpreter for the ADR index check (default: python3)
set -uo pipefail

MARKDOWNLINT_CLI2_VERSION="${MARKDOWNLINT_CLI2_VERSION:-0.18.1}"
LYCHEE_IMAGE="${LYCHEE_IMAGE:-lycheeverse/lychee:0.24.2}"
LINKS_ONLINE="${LINKS_ONLINE:-0}"
PYTHON="${PYTHON:-python3}"
ALL_CHECKS=(markdownlint mermaid links adr-index)

ROOT="$(git -C "$(dirname "${BASH_SOURCE[0]}")" rev-parse --show-toplevel)" || exit 2
cd "$ROOT" || exit 2
SCRIPTS="$ROOT/scripts"

check_markdownlint() {
  npx --yes "markdownlint-cli2@${MARKDOWNLINT_CLI2_VERSION}"
}

check_mermaid() {
  "$SCRIPTS/check_mermaid.sh"
}

lychee_cmd() {
  if [[ -n "${LYCHEE:-}" ]]; then
    echo "$LYCHEE"
  elif command -v lychee >/dev/null 2>&1; then
    echo lychee
  elif command -v docker >/dev/null 2>&1; then
    echo "docker run --rm --user $(id -u):$(id -g) -v $ROOT:$ROOT -w $ROOT $LYCHEE_IMAGE"
  else
    echo "links: lychee not found; install it (https://lychee.cli.rs/installation/) or Docker" >&2
    return 1
  fi
}

check_links() {
  local cmd mode=()
  cmd="$(lychee_cmd)" || return 1
  [[ "$LINKS_ONLINE" == "1" ]] || mode=(--offline)
  # shellcheck disable=SC2086  # $cmd is a command line, word splitting is intended
  $cmd --config lychee.toml --no-progress --root-dir "$ROOT" "${mode[@]}" './**/*.md'
}

check_adr_index() {
  "$PYTHON" "$SCRIPTS/check_adr_index.py" --root "$ROOT" &&
    "$PYTHON" -m unittest discover --start-directory "$SCRIPTS/tests" --pattern 'test_check_adr_index.py'
}

checks=("$@")
((${#checks[@]} > 0)) || checks=("${ALL_CHECKS[@]}")

failed=()
for check in "${checks[@]}"; do
  case "$check" in
    markdownlint | mermaid | links | adr-index) ;;
    *)
      echo "unknown check '$check' (expected one of: ${ALL_CHECKS[*]})" >&2
      exit 2
      ;;
  esac
  echo "==> $check"
  start=$SECONDS
  if "check_${check//-/_}"; then
    echo "<== $check: ok ($((SECONDS - start))s)"
  else
    echo "<== $check: FAILED ($((SECONDS - start))s)" >&2
    failed+=("$check")
  fi
done

if ((${#failed[@]} > 0)); then
  echo "docs-check failed: ${failed[*]}" >&2
  exit 1
fi
echo "docs-check passed: ${checks[*]}"
