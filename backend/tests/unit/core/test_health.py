"""Unit tests for :mod:`roboprobe.core.health` (server on an ephemeral port)."""

from __future__ import annotations

import json
import urllib.error
import urllib.request
from collections.abc import Iterator

import pytest

from roboprobe.core.errors import StoreError
from roboprobe.core.health import (
    HEALTH_PATH,
    METRICS_PATH,
    Check,
    HealthServer,
    run_checks,
    serve_health,
)
from roboprobe.core.metrics_registry import create_metrics

pytestmark = pytest.mark.unit

LOOPBACK = "127.0.0.1"
DSN = "postgresql://rp:hunter2@db/rp"


def _ok() -> None:
    return None


def _broken_driver() -> None:
    raise ConnectionError(DSN)


def _stale_heartbeat() -> None:
    msg = "heartbeat older than timeout"
    raise StoreError(msg)


def _get(server: HealthServer, path: str) -> tuple[int, str, bytes]:
    url = f"http://{LOOPBACK}:{server.port}{path}"
    try:
        with urllib.request.urlopen(url, timeout=5) as response:
            return response.status, response.headers["Content-Type"], response.read()
    except urllib.error.HTTPError as err:
        return err.code, err.headers["Content-Type"], err.read()


@pytest.fixture
def healthy_server() -> Iterator[HealthServer]:
    metrics = create_metrics(enabled=True)
    metrics.queue_depth.labels(backend="kinematic2d").set(3)
    with serve_health(LOOPBACK, 0, [Check("db", _ok)], metrics) as server:
        yield server


def test_run_checks_aggregates_and_runs_every_check() -> None:
    report = run_checks([Check("a", _ok), Check("b", _broken_driver), Check("c", _stale_heartbeat)])
    assert not report.healthy
    assert [(c.name, c.healthy) for c in report.checks] == [
        ("a", True),
        ("b", False),
        ("c", False),
    ]


def test_failure_details_never_echo_third_party_messages() -> None:
    report = run_checks([Check("db", _broken_driver), Check("hb", _stale_heartbeat)])
    db, hb = report.checks
    assert db.detail == "ConnectionError"
    assert "hunter2" not in report.model_dump_json()
    assert hb.detail == "STORE_ERROR: heartbeat older than timeout"


def test_no_checks_is_healthy() -> None:
    assert run_checks([]).healthy


def test_healthz_returns_200_when_all_checks_pass(healthy_server: HealthServer) -> None:
    status, content_type, body = _get(healthy_server, HEALTH_PATH)
    assert status == 200
    assert content_type == "application/json"
    assert json.loads(body) == {
        "healthy": True,
        "checks": [{"name": "db", "healthy": True, "detail": None}],
    }


def test_healthz_ignores_query_strings(healthy_server: HealthServer) -> None:
    assert _get(healthy_server, f"{HEALTH_PATH}?probe=docker")[0] == 200


def test_healthz_returns_503_with_details_when_a_check_fails() -> None:
    checks = [Check("db", _ok), Check("heartbeat", _stale_heartbeat)]
    with serve_health(LOOPBACK, 0, checks, create_metrics(enabled=True)) as server:
        status, _, body = _get(server, HEALTH_PATH)
    assert status == 503
    report = json.loads(body)
    assert report["healthy"] is False
    assert report["checks"][1]["detail"] == "STORE_ERROR: heartbeat older than timeout"


def test_metrics_endpoint_serves_the_exposition(healthy_server: HealthServer) -> None:
    status, content_type, body = _get(healthy_server, METRICS_PATH)
    assert status == 200
    assert content_type.startswith("text/plain")
    assert b'roboprobe_queue_depth{backend="kinematic2d"} 3.0' in body


def test_metrics_endpoint_is_absent_when_disabled() -> None:
    with serve_health(LOOPBACK, 0, [], create_metrics(enabled=False)) as server:
        assert _get(server, METRICS_PATH)[0] == 404
        assert _get(server, HEALTH_PATH)[0] == 200


def test_unknown_path_is_404(healthy_server: HealthServer) -> None:
    assert _get(healthy_server, "/nope")[0] == 404


def test_stopped_server_releases_its_port() -> None:
    server = serve_health(LOOPBACK, 0, [], create_metrics(enabled=False))
    port = server.port
    server.stop()
    with serve_health(LOOPBACK, port, [], create_metrics(enabled=False)) as again:
        assert again.port == port
