"""Unit tests for :mod:`roboprobe.core.metrics_registry` (docs/21 §5.2)."""

from __future__ import annotations

import pytest
from prometheus_client.parser import text_string_to_metric_families

from roboprobe.core.metrics_registry import create_metrics

pytestmark = pytest.mark.unit

# docs/21 §5.2, verbatim: name -> (type, labels).
SPEC: dict[str, tuple[str, tuple[str, ...]]] = {
    "roboprobe_runs_total": ("counter", ("backend", "verdict", "primary_failure")),
    "roboprobe_run_duration_seconds": ("histogram", ("backend", "phase")),
    "roboprobe_queue_depth": ("gauge", ("backend",)),
    "roboprobe_workers": ("gauge", ("backend", "status")),
    "roboprobe_selector_propose_seconds": ("histogram", ("strategy",)),
    "roboprobe_analysis_step_seconds": ("histogram", ("step",)),
    "roboprobe_gp_fit_seconds": ("histogram", ()),
    "roboprobe_episode_rtf": ("histogram", ("backend",)),
    "roboprobe_infra_errors_total": ("counter", ("backend", "reason")),
    "roboprobe_api_request_duration_seconds": ("histogram", ("route", "method", "status")),
}


def _registered() -> dict[str, tuple[str, tuple[str, ...]]]:
    metrics = create_metrics(enabled=True)
    assert metrics.registry is not None
    found: dict[str, tuple[str, tuple[str, ...]]] = {}
    # prometheus_client exposes label names only via private attributes; stable since 0.x.
    for collector in metrics.registry._collector_to_names:
        name = collector._name
        kind = collector._type
        full = f"{name}_total" if kind == "counter" else name
        found[full] = (kind, tuple(collector._labelnames))
    return found


def test_every_documented_metric_is_registered_with_exact_type_and_labels() -> None:
    assert _registered() == SPEC


def test_exposition_contains_recorded_samples() -> None:
    metrics = create_metrics(enabled=True)
    metrics.runs_total.labels(backend="kinematic2d", verdict="FAIL", primary_failure="F-COL").inc()
    metrics.gp_fit_seconds.observe(0.3)
    metrics.queue_depth.labels(backend="kinematic2d").set(4)
    families = {f.name: f for f in text_string_to_metric_families(metrics.exposition().decode())}
    (run_sample,) = [s for s in families["roboprobe_runs"].samples if s.name.endswith("_total")]
    assert run_sample.labels == {
        "backend": "kinematic2d",
        "verdict": "FAIL",
        "primary_failure": "F-COL",
    }
    assert run_sample.value == 1
    assert families["roboprobe_queue_depth"].samples[0].value == 4


def test_each_call_uses_an_isolated_registry() -> None:
    first, second = create_metrics(enabled=True), create_metrics(enabled=True)
    first.infra_errors_total.labels(backend="k2d", reason="crash").inc()
    assert b'reason="crash"' in first.exposition()
    assert b'reason="crash"' not in second.exposition()


def test_disabled_metrics_are_a_silent_null_object() -> None:
    metrics = create_metrics(enabled=False)
    assert not metrics.enabled
    metrics.runs_total.labels(backend="k2d", verdict="PASS", primary_failure="").inc()
    metrics.run_duration_seconds.labels(backend="k2d", phase="episode").observe(1.0)
    metrics.workers.labels(backend="k2d", status="idle").set(2)
    assert metrics.exposition() == b""
