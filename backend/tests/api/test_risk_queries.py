"""Stored NPZ slices are returned with physical axes and exact cache keys (T-082b)."""

from __future__ import annotations

import threading
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import numpy as np
import pytest
from fastapi.testclient import TestClient
from tests.api.test_campaigns_crud import body
from tests.api.test_campaigns_crud import client as client  # noqa: PLC0414 - shared fixture

from roboprobe.api import risk_queries
from roboprobe.core.types import RunStatus, Verdict
from roboprobe.risk import RiskSlice, save_slices
from roboprobe.store.artifacts import LocalArtifactStore
from roboprobe.store.records import ArtifactRecord, RiskMapRecord

pytestmark = pytest.mark.unit
X = "robot.max_speed"
Y = "obstacle.clearance"


def seed(client: TestClient, tmp_path: Path) -> UUID:
    cid = UUID(client.post("/api/v1/campaigns", json=body()).json()["id"])
    item = RiskSlice(
        x_param=X,
        y_param=Y,
        x_values=np.linspace(0.1, 0.6, 10),
        y_values=np.linspace(0.2, 1.0, 10),
        log_x=False,
        log_y=False,
        p_fail=np.full((10, 10), 0.2),
        mean=np.zeros((10, 10)),
        std=np.ones((10, 10)),
        region=np.ones((10, 10), dtype=np.int8),
        anchor={},
        grid_u=np.zeros((100, 6)),
    )
    path = tmp_path / "slices.npz"
    save_slices(path, [item])
    store = LocalArtifactStore(tmp_path / "artifacts")
    ref = store.put(path, "risk_slices", campaign_id=cid)
    client.app.state.services.artifact_store = store
    with client.app.state.services.uow_factory() as uow:
        uow.artifacts.add(ArtifactRecord(**ref.model_dump()))
        uow.risk_maps.add(
            RiskMapRecord(
                id=uuid4(),
                campaign_id=cid,
                n_obs=1,
                thresholds={},
                volumes={},
                robustness_score=0.5,
                slices_artifact=ref.id,
            )
        )
        uow.commit()
    return cid


def test_npz_slice_has_grid_and_second_call_uses_cache(
    client: TestClient, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    cid = seed(client, tmp_path)
    url = f"/api/v1/campaigns/{cid}/risk/slice"
    params = {"x": X, "y": Y, "resolution": 10}
    first = client.get(url, params=params)
    assert first.status_code == 200, first.text
    assert len(first.json()["x_values"]) == 10
    assert len(first.json()["p_fail"]) == 10
    assert first.json()["p_fail"][0][0] == 0.2
    monkeypatch.setattr(
        client.app.state.services.artifact_store, "open", lambda _: pytest.fail("cache missed")
    )
    assert client.get(url, params=params).json() == first.json()


@pytest.mark.parametrize(
    "params",
    [
        {"x": X, "y": X, "resolution": 10},
        {"x": X, "y": Y, "resolution": 100000},
        {"x": "unknown", "y": Y, "resolution": 10},
    ],
)
def test_invalid_axes_or_resolution_are_422(
    client: TestClient, tmp_path: Path, params: dict[str, object]
) -> None:
    cid = seed(client, tmp_path)
    assert client.get(f"/api/v1/campaigns/{cid}/risk/slice", params=params).status_code == 422


def test_other_resolution_refits_once_and_includes_observations(
    client: TestClient,
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    cid = seed(client, tmp_path)
    result = client.post(f"/api/v1/campaigns/{cid}/runs", json={"values": {}})
    assert result.status_code == 201
    rid = UUID(result.json()["run_ids"][0])
    with client.app.state.services.uow_factory() as uow:
        row = uow.runs.get(rid)
        uow.runs.import_many(
            [
                row.model_copy(
                    update={"status": RunStatus.DONE, "verdict": Verdict.FAIL, "robustness": -0.1}
                )
            ]
        )
        uow.commit()
    fits = []

    class FakeGP:
        def __init__(self, *args: object, **kwargs: object) -> None:
            pass

        def fit(self, x: np.ndarray, y: np.ndarray) -> None:
            fits.append(len(y))

        def predict(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            return np.zeros(len(x)), np.ones(len(x))

        def predict_total_std(self, x: np.ndarray) -> np.ndarray:
            return np.ones(len(x))

    original = risk_queries.importlib.import_module
    monkeypatch.setattr(
        risk_queries.importlib,
        "import_module",
        lambda name, *a, **kw: (
            SimpleNamespace(RobustnessGP=FakeGP)
            if name == "roboprobe.selection.surrogate"
            else original(name, *a, **kw)
        ),
    )
    params = {"x": X, "y": Y, "resolution": 11}
    url = f"/api/v1/campaigns/{cid}/risk/slice"
    first = client.get(url, params=params)
    assert first.status_code == 200, first.text
    assert len(first.json()["p_fail"]) == 11
    assert first.json()["points"][0]["run_id"] == str(rid)
    assert client.get(url, params=params).json() == first.json()
    assert fits == [1]


def test_health_responds_while_slice_computation_is_running(
    api_client: TestClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:

    started = threading.Event()
    release = threading.Event()

    def slow_slice(  # noqa: PLR0913, PLR0917 - matches slice service port
        self: object, campaign_id: UUID, x: str, y: str, anchor: str, resolution: int
    ) -> dict[str, object]:
        started.set()
        release.wait(timeout=10)
        return {"x_param": x, "y_param": y, "anchor": anchor, "resolution": resolution}

    monkeypatch.setattr(risk_queries.RiskQueries, "slice", slow_slice)
    with ThreadPoolExecutor(max_workers=2) as pool:
        work = pool.submit(
            api_client.get,
            f"/api/v1/campaigns/{uuid4()}/risk/slice",
            params={"x": X, "y": Y, "resolution": 10},
        )
        try:
            assert started.wait(timeout=2)
            health = pool.submit(api_client.get, "/health/live")
            assert health.result(timeout=2).status_code == 200
        finally:
            release.set()
        assert work.result(timeout=5).status_code == 200
