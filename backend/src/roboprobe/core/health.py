"""Liveness/readiness checks and a tiny internal ``/healthz`` + ``/metrics`` HTTP server.

Workers and the orchestrator (which have no web framework) call :func:`serve_health` from their
composition root; the API reuses :func:`run_checks` behind its own routes (docs/21 §5.4).

A check is any object with a ``name`` that raises when unhealthy. Failure details never echo raw
exception text from third-party errors (it may contain DSNs); only RoboProbe errors, whose
messages are secret-free by contract, are shown verbatim.

Layer: Kernel (L1).

Implements: docs/21 §5.4, NFR-OBS-001
"""

from __future__ import annotations

import threading
from collections.abc import Callable, Iterable
from dataclasses import dataclass
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from types import TracebackType
from typing import Final, Protocol, Self
from urllib.parse import urlsplit

from prometheus_client import CONTENT_TYPE_LATEST
from pydantic import BaseModel, ConfigDict

from roboprobe.core.errors import RoboProbeError
from roboprobe.core.metrics_registry import Metrics

__all__ = [
    "HEALTH_PATH",
    "METRICS_PATH",
    "Check",
    "CheckOutcome",
    "HealthCheck",
    "HealthReport",
    "HealthServer",
    "run_checks",
    "serve_health",
]

HEALTH_PATH: Final = "/healthz"
METRICS_PATH: Final = "/metrics"
_JSON_CONTENT_TYPE: Final = "application/json"


class HealthCheck(Protocol):
    """A named probe; calling it returns normally when healthy and raises otherwise."""

    @property
    def name(self) -> str:
        """Stable check name shown in reports (e.g. ``"heartbeat"``)."""
        ...

    def __call__(self) -> None:
        """Probe the dependency; raise any exception to report it unhealthy."""
        ...


@dataclass(frozen=True, slots=True)
class Check:
    """Adapter turning a plain callable into a :class:`HealthCheck`."""

    name: str
    probe: Callable[[], None]

    def __call__(self) -> None:
        """Run the probe."""
        self.probe()


class CheckOutcome(BaseModel):
    """Result of one check."""

    model_config = ConfigDict(frozen=True)

    name: str
    healthy: bool
    detail: str | None = None


class HealthReport(BaseModel):
    """Aggregate of all checks; healthy only if every check is (an empty set is healthy)."""

    model_config = ConfigDict(frozen=True)

    healthy: bool
    checks: tuple[CheckOutcome, ...]


def _describe_failure(exc: Exception) -> str:
    if isinstance(exc, RoboProbeError):
        return str(exc)
    return type(exc).__name__


def run_checks(checks: Iterable[HealthCheck]) -> HealthReport:
    """Run every check (sequentially, all of them) and aggregate the outcomes.

    Args:
        checks: Checks to run; an exception from one does not stop the others.

    Returns:
        The aggregated :class:`HealthReport`.
    """
    outcomes: list[CheckOutcome] = []
    for check in checks:
        try:
            check()
        # Health is a boundary: any failure of a probe is reported, never propagated.
        except Exception as exc:
            outcomes.append(
                CheckOutcome(name=check.name, healthy=False, detail=_describe_failure(exc))
            )
        else:
            outcomes.append(CheckOutcome(name=check.name, healthy=True))
    return HealthReport(healthy=all(o.healthy for o in outcomes), checks=tuple(outcomes))


def _make_handler(
    checks: tuple[HealthCheck, ...], metrics: Metrics
) -> type[BaseHTTPRequestHandler]:
    class _Handler(BaseHTTPRequestHandler):
        def do_GET(self) -> None:
            path = urlsplit(self.path).path
            if path == HEALTH_PATH:
                report = run_checks(checks)
                status = HTTPStatus.OK if report.healthy else HTTPStatus.SERVICE_UNAVAILABLE
                self._reply(status, _JSON_CONTENT_TYPE, report.model_dump_json().encode())
            elif path == METRICS_PATH and metrics.enabled:
                self._reply(HTTPStatus.OK, CONTENT_TYPE_LATEST, metrics.exposition())
            else:
                self.send_error(HTTPStatus.NOT_FOUND)

        def _reply(self, status: HTTPStatus, content_type: str, body: bytes) -> None:
            self.send_response(status)
            self.send_header("Content-Type", content_type)
            self.send_header("Content-Length", str(len(body)))
            self.end_headers()
            self.wfile.write(body)

        def log_message(self, format: str, *args: object) -> None:  # noqa: A002 - stdlib signature
            """Silence per-request access logs (probes hit this every few seconds)."""

    return _Handler


class HealthServer:
    """A running health server; stop it with :meth:`stop` or use it as a context manager."""

    def __init__(self, server: ThreadingHTTPServer) -> None:
        """Start serving ``server`` on a daemon thread."""
        self._server = server
        self._thread = threading.Thread(
            target=server.serve_forever, name="roboprobe-health", daemon=True
        )
        self._thread.start()

    @property
    def port(self) -> int:
        """Bound port (useful when started on port 0)."""
        return int(self._server.server_address[1])

    def stop(self) -> None:
        """Stop serving and release the socket."""
        self._server.shutdown()
        self._server.server_close()
        self._thread.join()

    def __enter__(self) -> Self:
        """Return the running server."""
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc: BaseException | None,
        tb: TracebackType | None,
    ) -> None:
        """Stop the server."""
        self.stop()


def serve_health(
    host: str, port: int, checks: Iterable[HealthCheck], metrics: Metrics
) -> HealthServer:
    """Serve ``GET /healthz`` (200 or 503 with a JSON report) and ``GET /metrics``.

    Args:
        host: Bind address chosen by the composition root.
        port: Port, normally ``worker.health_port``; ``0`` picks a free port.
        checks: Checks run on every ``/healthz`` request.
        metrics: Metric set; ``/metrics`` returns 404 when it is disabled.

    Returns:
        The running :class:`HealthServer`.
    """
    handler = _make_handler(tuple(checks), metrics)
    return HealthServer(ThreadingHTTPServer((host, port), handler))
