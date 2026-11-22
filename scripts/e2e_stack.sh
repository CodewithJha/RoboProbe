#!/usr/bin/env bash
# Run a command against a disposable Compose project and clean up afterwards.
set -euo pipefail
root="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
exec node "$root/web/e2e/with-stack.ts" "$@"
