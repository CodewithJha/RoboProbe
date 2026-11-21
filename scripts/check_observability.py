"""Validate the observability profile: dashboard JSON and Prometheus metric names.

Every ``roboprobe_*`` series used by the Grafana dashboard must be defined in
``roboprobe.core.metrics_registry`` (T-125). Histogram ``_bucket`` / ``_sum`` / ``_count``
suffixes are stripped before the check.

Implements: T-125, NFR-OBS-002
"""

from __future__ import annotations

import json
import re
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
DASHBOARD = REPO_ROOT / "docker/observability/grafana/dashboards/roboprobe.json"
PROMETHEUS = REPO_ROOT / "docker/observability/prometheus.yml"
REGISTRY = REPO_ROOT / "backend/src/roboprobe/core/metrics_registry.py"

_SERIES = re.compile(r"roboprobe_[a-z0-9_]+")
_DEFINED = re.compile(r'"(roboprobe_[a-z0-9_]+)"')
_HISTOGRAM_SUFFIXES = ("_bucket", "_sum", "_count")
_REQUIRED_JOBS = ("roboprobe-api", "roboprobe-orchestrator", "roboprobe-worker")
_SCRAPE_INTERVAL = "scrape_interval: 15s"


def _base_name(series: str) -> str:
    for suffix in _HISTOGRAM_SUFFIXES:
        if series.endswith(suffix):
            return series[: -len(suffix)]
    return series


def dashboard_series(dashboard: dict[str, object]) -> set[str]:
    """Return base metric names referenced by dashboard panel expressions."""
    found: set[str] = set()
    panels = dashboard.get("panels")
    if not isinstance(panels, list):
        msg = "dashboard has no panels array"
        raise SystemExit(msg)
    for panel in panels:
        if not isinstance(panel, dict):
            continue
        targets = panel.get("targets")
        if not isinstance(targets, list):
            continue
        for target in targets:
            if not isinstance(target, dict):
                continue
            expr = target.get("expr")
            if isinstance(expr, str):
                found.update(_base_name(match) for match in _SERIES.findall(expr))
    return found


def main() -> None:
    """Exit non-zero when the dashboard or Prometheus config is inconsistent."""
    dashboard_text = DASHBOARD.read_text(encoding="utf-8")
    dashboard = json.loads(dashboard_text)
    if not isinstance(dashboard, dict):
        msg = "dashboard JSON must be an object"
        raise SystemExit(msg)
    if dashboard.get("title") != "RoboProbe" or dashboard.get("uid") != "roboprobe-overview":
        msg = "dashboard title/uid mismatch"
        raise SystemExit(msg)
    prom = PROMETHEUS.read_text(encoding="utf-8")
    if _SCRAPE_INTERVAL not in prom:
        msg = "prometheus.yml must set scrape_interval to 15s"
        raise SystemExit(msg)
    missing_jobs = [job for job in _REQUIRED_JOBS if f"job_name: {job}" not in prom]
    if missing_jobs:
        msg = f"prometheus.yml missing jobs: {', '.join(missing_jobs)}"
        raise SystemExit(msg)
    defined = set(_DEFINED.findall(REGISTRY.read_text(encoding="utf-8")))
    used = dashboard_series(dashboard)
    unknown = sorted(used - defined)
    if unknown:
        msg = f"dashboard uses metrics missing from the registry: {', '.join(unknown)}"
        raise SystemExit(msg)
    if not used:
        msg = "dashboard has no roboprobe_* series"
        raise SystemExit(msg)
    print(f"ok: {len(used)} dashboard metrics are in the registry")


if __name__ == "__main__":
    main()
