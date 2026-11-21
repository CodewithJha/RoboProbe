"""Trace transport preserves safety events and confines downloads (T-081e)."""

from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import numpy as np
import pyarrow as pa
import pyarrow.parquet as pq
import pytest
import structlog.testing
from fastapi.testclient import TestClient
from hypothesis import given
from hypothesis import strategies as st

from roboprobe.api.downsample import sample_indices
from roboprobe.core.errors import ValidationError
from roboprobe.store.artifacts import LocalArtifactStore

pytestmark = pytest.mark.unit


@given(st.lists(st.floats(min_value=-10, max_value=10, allow_nan=False), min_size=2, max_size=200))
def test_downsample_preserves_global_minimum(clearances: list[float]) -> None:
    t = np.arange(len(clearances)) / 20
    values = np.asarray(clearances)
    indices = sample_indices(t, values, {}, hz=3)
    assert values[indices].min() == values.min()
    assert np.all(np.diff(indices) > 0)


def test_flag_transitions_survive_a_single_bucket() -> None:
    t = np.arange(20) / 100
    flags = np.asarray([False] * 7 + [True] + [False] * 12)
    indices = sample_indices(t, np.ones(20), {"contact": flags}, hz=1)
    assert {6, 7, 8} <= set(indices)


@pytest.fixture
def trace_client(api_client: TestClient, tmp_path: Path):
    run_id, artifact_id = uuid4(), uuid4()
    source = tmp_path / "trace.parquet"
    clearance = np.ones(40)
    clearance[17] = -0.5
    pq.write_table(
        pa.table(
            {
                "t": np.arange(40) / 20,
                "min_obstacle_dist": clearance,
                "contact": [False] * 17 + [True] + [False] * 22,
                "gt_x": np.arange(40) / 10,
            }
        ),
        source,
    )
    store = LocalArtifactStore(tmp_path / "artifacts")
    ref = store.put(source, "trace", run_id=run_id)
    artifact = SimpleNamespace(**{**ref.model_dump(), "id": artifact_id})
    run = SimpleNamespace(id=run_id, ordinal=7)
    uow = SimpleNamespace(
        runs=SimpleNamespace(get=lambda rid: run if rid == run_id else None),
        artifacts=SimpleNamespace(
            get=lambda aid: artifact if aid == artifact_id else None,
            list_for_run=lambda rid: [artifact],
        ),
        close=lambda: None,
    )
    api_client.app.state.services.uow_factory = lambda: uow
    api_client.app.state.services.artifact_store = store
    return api_client, run, artifact, store


def test_json_trace_preserves_contacts_and_clearance(trace_client) -> None:
    client, run, _, _ = trace_client
    response = client.get(f"/api/v1/runs/{run.id}/trace?hz=3&columns=contact,min_obstacle_dist")
    assert response.status_code == 200, response.text
    body = response.json()
    assert body["hz"] == 3
    assert body["source_hz"] == pytest.approx(20)
    assert min(body["columns"]["min_obstacle_dist"]) == -0.5
    assert any(body["columns"]["contact"])
    assert set(body["columns"]) == {"contact", "min_obstacle_dist"}
    assert body["truncated"] is True


def test_rate_cap_and_bad_columns(trace_client) -> None:
    client, run, _, _ = trace_client
    response = client.get(f"/api/v1/runs/{run.id}/trace?hz=1000")
    assert response.status_code == 200
    assert response.json()["hz"] == 50
    assert response.json()["truncated"] is True
    assert client.get(f"/api/v1/runs/{run.id}/trace?columns=unknown").status_code == 422
    assert client.get(f"/api/v1/runs/{run.id}/trace?hz=0").status_code == 422


def test_parquet_and_artifacts_stream_with_safe_headers(trace_client, monkeypatch) -> None:
    client, run, artifact, store = trace_client
    monkeypatch.setattr(
        store, "open", lambda _: pytest.fail("download must use a confined FileResponse")
    )
    response = client.get(
        f"/api/v1/runs/{run.id}/trace", headers={"Accept": "application/vnd.apache.parquet"}
    )
    assert response.status_code == 200
    assert response.content[:4] == b"PAR1"
    assert response.headers["etag"] == f'"{artifact.sha256}"'
    assert response.headers["x-content-type-options"] == "nosniff"
    assert "7-trace.parquet" in response.headers["content-disposition"]
    direct = client.get(f"/api/v1/artifacts/{artifact.id}/content")
    assert direct.content == response.content
    assert client.get(f"/api/v1/runs/{run.id}/artifacts").status_code == 200


def test_crafted_db_path_is_not_found_and_logged(trace_client, tmp_path: Path) -> None:
    client, _, artifact, _ = trace_client
    secret = tmp_path / "private.txt"
    secret.write_text("do not return this")
    artifact.rel_path = str(secret)
    with structlog.testing.capture_logs() as logs:
        response = client.get(f"/api/v1/artifacts/{artifact.id}/content")
    assert response.status_code == 404
    assert "do not return this" not in response.text
    assert any(row["event"] == "artifact.path_rejected" for row in logs)


def test_unknown_run_and_artifact_return_404(trace_client) -> None:
    client, _, _, _ = trace_client
    assert client.get(f"/api/v1/runs/{uuid4()}/trace").status_code == 404
    assert client.get(f"/api/v1/artifacts/{uuid4()}/content").status_code == 404


@pytest.mark.parametrize("hz", [0, -1, float("inf"), float("nan")])
def test_invalid_sample_rate_is_rejected(hz: float) -> None:
    with pytest.raises(ValidationError):
        sample_indices(np.asarray([0.0, 1.0]), np.ones(2), {}, hz=hz)


def test_empty_trace_and_invalid_columns() -> None:
    empty = np.asarray([], dtype=np.float64)
    assert not len(sample_indices(empty, empty, {}, hz=10))
    with pytest.raises(ValidationError):
        sample_indices(np.asarray([0.0, 0.0]), np.ones(2), {}, hz=1)
    with pytest.raises(ValidationError):
        sample_indices(np.asarray([0.0, 1.0]), np.ones(2), {"contact": np.ones(3)}, hz=1)


def test_attachment_filename_does_not_trust_database_kind(trace_client) -> None:
    client, _, artifact, _ = trace_client
    artifact.kind = "../../trace\r\n"
    response = client.get(f"/api/v1/artifacts/{artifact.id}/content")
    assert response.status_code == 200
    disposition = response.headers["content-disposition"]
    assert "../" not in disposition
    assert "\r" not in disposition and "\n" not in disposition


def test_openapi_describes_json_and_parquet(trace_client) -> None:
    client, _, _, _ = trace_client
    schema = client.app.openapi()
    content = schema["paths"]["/api/v1/runs/{run_id}/trace"]["get"]["responses"]["200"]["content"]
    assert content["application/json"]["schema"]["$ref"].endswith("/TraceOut")
    assert content["application/vnd.apache.parquet"]["schema"]["format"] == "binary"
