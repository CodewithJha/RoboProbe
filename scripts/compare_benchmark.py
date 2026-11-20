#!/usr/bin/env python3
r"""Compare a weekly benchmark JSON against a committed baseline (T-064).

Exit 0 when every reported metric stays within ``tolerance`` relative regression
of the baseline; exit 1 on regression; exit 2 on usage/input errors.

Usage (from repository root)::

    uv run --directory backend python ../scripts/compare_benchmark.py \
        backend/tests/benchmark/baselines/full_weekly.json /tmp/current.json \
        --tolerance 0.2 --summary
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any

EXIT_OK = 0
EXIT_REGRESSION = 1
EXIT_USAGE = 2

# Lower-is-better metrics (relative increase = regression).
_LOWER_BETTER = frozenset({"median_first_fail"})
# Higher-is-better metrics (relative decrease = regression).
_HIGHER_BETTER = frozenset({"mean_modes"})


def _load(path: Path) -> dict[str, Any]:
    try:
        raw = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        msg = f"failed to read {path}: {exc}"
        raise SystemExit(msg) from exc
    if not isinstance(raw, dict):
        msg = f"{path} must be a JSON object"
        raise SystemExit(msg)
    return raw


def _results(doc: dict[str, Any]) -> dict[str, dict[str, Any]]:
    block = doc.get("results", doc)
    if not isinstance(block, dict):
        msg = "missing results mapping"
        raise SystemExit(msg)
    out: dict[str, dict[str, Any]] = {}
    for key, value in block.items():
        if isinstance(value, dict):
            out[str(key)] = value
    return out


def compare(
    baseline: dict[str, Any],
    current: dict[str, Any],
    *,
    tolerance: float,
) -> list[str]:
    """Return human-readable regression lines (empty = ok)."""
    base_rows = _results(baseline)
    cur_rows = _results(current)
    failures: list[str] = []
    for key, base in sorted(base_rows.items()):
        if key not in cur_rows:
            failures.append(f"{key}: missing from current results")
            continue
        cur = cur_rows[key]
        for metric in sorted(_LOWER_BETTER | _HIGHER_BETTER):
            if metric not in base:
                continue
            base_val = base.get(metric)
            cur_val = cur.get(metric)
            if not isinstance(base_val, (int, float)) or not isinstance(cur_val, (int, float)):
                failures.append(f"{key}.{metric}: non-numeric ({base_val!r} vs {cur_val!r})")
                continue
            if base_val == 0:
                continue
            if metric in _LOWER_BETTER:
                limit = float(base_val) * (1.0 + tolerance)
                if float(cur_val) > limit:
                    failures.append(
                        f"{key}.{metric}: {cur_val} > {limit:.4g} "
                        f"(baseline {base_val}, tol {tolerance})"
                    )
            else:
                limit = float(base_val) * (1.0 - tolerance)
                if float(cur_val) < limit:
                    failures.append(
                        f"{key}.{metric}: {cur_val} < {limit:.4g} "
                        f"(baseline {base_val}, tol {tolerance})"
                    )
    return failures


def _markdown(baseline: Path, current: Path, failures: list[str], tolerance: float) -> str:
    status = "FAIL" if failures else "PASS"
    lines = [
        f"### Weekly benchmark compare — **{status}**",
        "",
        f"- baseline: `{baseline}`",
        f"- current: `{current}`",
        f"- tolerance: {tolerance}",
        "",
    ]
    if failures:
        lines.append("Regressions:")
        lines.extend(f"- {item}" for item in failures)
    else:
        lines.append("No regressions beyond tolerance.")
    return "\n".join(lines) + "\n"


def main(argv: list[str] | None = None) -> int:
    """CLI entry: compare baseline vs current benchmark JSON."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("baseline", type=Path)
    parser.add_argument("current", type=Path)
    parser.add_argument(
        "--tolerance",
        type=float,
        default=0.2,
        help="Allowed relative regression (default 0.2 = 20%%).",
    )
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a markdown summary to stdout.",
    )
    args = parser.parse_args(argv)
    if args.tolerance < 0.0:
        print("tolerance must be >= 0", file=sys.stderr)
        return EXIT_USAGE
    try:
        baseline = _load(args.baseline)
        current = _load(args.current)
        failures = compare(baseline, current, tolerance=args.tolerance)
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return EXIT_USAGE
    if args.summary:
        print(_markdown(args.baseline, args.current, failures, args.tolerance), end="")
    if failures:
        for line in failures:
            print(line, file=sys.stderr)
        return EXIT_REGRESSION
    return EXIT_OK


if __name__ == "__main__":
    raise SystemExit(main())
