#!/usr/bin/env python3
"""Write the OpenAPI snapshot from the FastAPI app (T-084b, FR-API-001).

Uses default settings (no environment files) so two runs are byte-identical.
``make openapi`` writes ``api/openapi.json``; ``--check`` fails when the file drifted.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

from roboprobe.api.app import create_app
from roboprobe.core.settings import RoboProbeSettings

_REPO = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT = _REPO / "api" / "openapi.json"


def render_openapi() -> str:
    """Return the canonical OpenAPI document, including a trailing newline."""
    spec: dict[str, Any] = create_app(RoboProbeSettings()).openapi()
    return json.dumps(spec, indent=2, sort_keys=True) + "\n"


def main(argv: list[str] | None = None) -> int:
    """Write or check ``api/openapi.json``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--output", type=Path, default=_DEFAULT_OUTPUT)
    parser.add_argument(
        "--check",
        action="store_true",
        help="Exit 1 when the snapshot does not match the app.",
    )
    args = parser.parse_args(argv)
    rendered = render_openapi()
    if args.check:
        current = args.output.read_text(encoding="utf-8") if args.output.is_file() else ""
        if current != rendered:
            print(f"{args.output} is stale; run make openapi", file=sys.stderr)
            return 1
        return 0
    args.output.parent.mkdir(parents=True, exist_ok=True)
    args.output.write_text(rendered, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
