"""Every Prometheus metric of docs/21 §5.2, defined once with its exact name, type and labels.

Services receive a :class:`Metrics` instance through dependency injection (never the global
default registry), so tests and multiple processes stay isolated and names/labels cannot drift.

Histogram bucket boundaries are *instrumentation constants*, not settings: they describe the
expected range of each quantity, changing them breaks dashboard/recording-rule continuity, and no
service needs a per-deployment override. Revisit (and add ``observability.*`` keys) only if one
does.

With ``observability.metrics_enabled = false`` :func:`create_metrics` returns a Null Object:
metric objects still accept ``inc``/``observe``/``set`` calls but belong to no registry, so
nothing is exported and callers need no ``if enabled`` branches.

Layer: Kernel (L1).

Implements: docs/21 §5.2, NFR-OBS-001
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Final

from prometheus_client import CollectorRegistry, Counter, Gauge, Histogram, generate_latest

__all__ = [
    "ANALYSIS_STEP_BUCKETS_S",
    "API_REQUEST_BUCKETS_S",
    "EPISODE_RTF_BUCKETS",
    "GP_FIT_BUCKETS_S",
    "RUN_DURATION_BUCKETS_S",
    "SELECTOR_PROPOSE_BUCKETS_S",
    "Metrics",
    "create_metrics",
]

RUN_DURATION_BUCKETS_S: Final = (1.0, 2.5, 5.0, 10.0, 20.0, 30.0, 60.0, 120.0, 300.0, 600.0)
"""Run phase durations [s]: k2d episodes take seconds, Gazebo episodes minutes."""
SELECTOR_PROPOSE_BUCKETS_S: Final = (0.01, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0)
"""Strategy ``propose`` latency [s] (target <= 2 s, NFR-PERF-002)."""
ANALYSIS_STEP_BUCKETS_S: Final = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 120.0)
"""Analysis pipeline step latency [s]."""
GP_FIT_BUCKETS_S: Final = (0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0, 10.0, 30.0, 60.0)
"""Surrogate (GP) fit time [s]; grows roughly cubically with observations."""
EPISODE_RTF_BUCKETS: Final = (0.1, 0.25, 0.5, 1.0, 2.0, 5.0, 10.0, 20.0, 50.0, 100.0)
"""Episode real-time factor (simulated / wall time): Gazebo < 1, kinematic2d >> 1."""
API_REQUEST_BUCKETS_S: Final = (0.005, 0.01, 0.025, 0.05, 0.1, 0.25, 0.5, 1.0, 2.5, 5.0)
"""API request latency [s] (p95 target 200 ms, NFR-PERF-004)."""


@dataclass(frozen=True, slots=True)
class Metrics:
    """The RoboProbe metric set (docs/21 §5.2) bound to one registry (``None`` when disabled).

    Attributes:
        registry: Registry the metrics are exported from; ``None`` for the disabled Null Object.
        runs_total: Finished runs. Labels: backend, verdict, primary_failure.
        run_duration_seconds: Run phase durations [s]. Labels: backend, phase.
        queue_depth: Pending runs. Labels: backend.
        workers: Worker processes. Labels: backend, status.
        selector_propose_seconds: Strategy ``propose`` latency [s]. Labels: strategy.
        analysis_step_seconds: Analysis pipeline step latency [s]. Labels: step.
        gp_fit_seconds: Surrogate fit time [s]. No labels.
        episode_rtf: Episode real-time factor. Labels: backend.
        infra_errors_total: Infrastructure errors. Labels: backend, reason.
        api_request_duration_seconds: API request latency [s]. Labels: route, method, status.
        sse_clients: Connected SSE subscribers. No labels.
        sse_reconnects_total: LISTEN connection recoveries. No labels.
    """

    registry: CollectorRegistry | None
    runs_total: Counter
    run_duration_seconds: Histogram
    queue_depth: Gauge
    workers: Gauge
    selector_propose_seconds: Histogram
    analysis_step_seconds: Histogram
    gp_fit_seconds: Histogram
    episode_rtf: Histogram
    infra_errors_total: Counter
    api_request_duration_seconds: Histogram
    sse_clients: Gauge
    sse_reconnects_total: Counter

    @property
    def enabled(self) -> bool:
        """Whether the metrics are exported."""
        return self.registry is not None

    def exposition(self) -> bytes:
        """Prometheus text exposition of every metric; empty when disabled."""
        return generate_latest(self.registry) if self.registry is not None else b""


def create_metrics(*, enabled: bool) -> Metrics:
    """Create the metric set in a fresh, dedicated registry.

    Args:
        enabled: ``observability.metrics_enabled``; ``False`` returns the Null Object.

    Returns:
        A new :class:`Metrics`; each call is independent (safe to call per test or process).
    """
    reg = CollectorRegistry() if enabled else None
    return Metrics(
        registry=reg,
        runs_total=Counter(
            "roboprobe_runs_total",
            "Finished runs by backend, verdict and primary failure class.",
            ("backend", "verdict", "primary_failure"),
            registry=reg,
        ),
        run_duration_seconds=Histogram(
            "roboprobe_run_duration_seconds",
            "Duration of run phases in seconds.",
            ("backend", "phase"),
            registry=reg,
            buckets=RUN_DURATION_BUCKETS_S,
        ),
        queue_depth=Gauge(
            "roboprobe_queue_depth", "Pending runs per backend.", ("backend",), registry=reg
        ),
        workers=Gauge(
            "roboprobe_workers",
            "Worker processes by backend and status.",
            ("backend", "status"),
            registry=reg,
        ),
        selector_propose_seconds=Histogram(
            "roboprobe_selector_propose_seconds",
            "Selection strategy propose latency in seconds.",
            ("strategy",),
            registry=reg,
            buckets=SELECTOR_PROPOSE_BUCKETS_S,
        ),
        analysis_step_seconds=Histogram(
            "roboprobe_analysis_step_seconds",
            "Analysis pipeline step latency in seconds.",
            ("step",),
            registry=reg,
            buckets=ANALYSIS_STEP_BUCKETS_S,
        ),
        gp_fit_seconds=Histogram(
            "roboprobe_gp_fit_seconds",
            "Gaussian-process surrogate fit time in seconds.",
            registry=reg,
            buckets=GP_FIT_BUCKETS_S,
        ),
        episode_rtf=Histogram(
            "roboprobe_episode_rtf",
            "Episode real-time factor (simulated time / wall time).",
            ("backend",),
            registry=reg,
            buckets=EPISODE_RTF_BUCKETS,
        ),
        infra_errors_total=Counter(
            "roboprobe_infra_errors_total",
            "Infrastructure errors by backend and reason.",
            ("backend", "reason"),
            registry=reg,
        ),
        api_request_duration_seconds=Histogram(
            "roboprobe_api_request_duration_seconds",
            "API request latency in seconds.",
            ("route", "method", "status"),
            registry=reg,
            buckets=API_REQUEST_BUCKETS_S,
        ),
        sse_clients=Gauge(
            "roboprobe_sse_clients",
            "Connected server-sent-event subscribers.",
            registry=reg,
        ),
        sse_reconnects_total=Counter(
            "roboprobe_sse_reconnects_total",
            "Times the outbox LISTEN connection was reopened.",
            registry=reg,
        ),
    )
