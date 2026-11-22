"""Check the nightly Locust CSV against the T-106 endpoint budgets."""

from __future__ import annotations

import argparse
import csv
import math
import sys
import tomllib
from pathlib import Path
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from collections.abc import Mapping


def _read_limits(path: Path) -> dict[str, float]:
    with path.open("rb") as stream:
        values = tomllib.load(stream).get("p95_ms")
    if not isinstance(values, dict) or not values:
        msg = "expected a nonempty [p95_ms] table"
        raise ValueError(msg)
    limits: dict[str, float] = {}
    for name, limit in values.items():
        if (
            isinstance(limit, bool)
            or not isinstance(limit, (int, float))
            or not math.isfinite(limit)
            or limit <= 0
        ):
            msg = f"expected a positive finite p95 limit for {name}"
            raise ValueError(msg)
        limits[name] = float(limit)
    return limits


def _grade(rows: list[dict[str, str]], limit: float) -> tuple[str, str, str, str]:
    if len(rows) != 1:
        return "-", "-", "-", "duplicate rows" if rows else "missing samples"
    row = rows[0]
    try:
        requests = int(row["Request Count"])
        failures = int(row["Failure Count"])
        p95 = float(row["95%"])
    except (KeyError, TypeError, ValueError):
        return "-", "-", "-", "invalid statistics"
    if requests < 0 or not (0 <= failures <= requests) or not math.isfinite(p95) or p95 < 0:
        return "-", "-", "-", "invalid statistics"
    if requests == 0:
        result = "no requests"
    elif failures:
        result = "request failures"
    elif p95 > limit:
        result = "p95 above limit"
    else:
        result = "PASS"
    return str(requests), str(failures), f"{p95:g}", result


def check(path: Path, limits: Mapping[str, float]) -> int:
    """Print the measured p95 values and return nonzero for any failed budget."""
    groups: dict[str, list[dict[str, str]]] = {name: [] for name in limits}
    with path.open(encoding="utf-8", newline="") as stream:
        for row in csv.DictReader(stream):
            name = row.get("Name")
            if row.get("Type") == "GET" and name is not None and name in groups:
                groups[name].append(row)

    width = max(map(len, groups), default=0) + len("GET ")
    print(
        f"{'Endpoint':<{width}}  {'Requests':>8}  {'Failures':>8}"
        f"  {'p95 (ms)':>8}  {'Limit':>6}  Result"
    )
    failed = False
    for name, limit in limits.items():
        requests, failures, p95, result = _grade(groups[name], limit)
        print(
            f"{f'GET {name}':<{width}}  {requests:>8}  {failures:>8}"
            f"  {p95:>8}  {limit:>6g}  {result}"
        )
        failed |= result != "PASS"
    return int(failed)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("stats", type=Path, help="Locust perf_stats.csv")
    parser.add_argument(
        "--thresholds", type=Path, default=Path(__file__).with_name("thresholds.toml")
    )
    args = parser.parse_args()
    try:
        return check(args.stats, _read_limits(args.thresholds))
    except (OSError, ValueError, csv.Error) as exc:
        print(f"Could not check Locust results: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
