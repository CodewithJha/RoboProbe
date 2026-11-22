"""SimulatorBackend contract suite (T-035d; docs/18 §4.3)."""

from __future__ import annotations

from pathlib import Path
from typing import Protocol
from uuid import uuid4

import pytest
from tests.factories import make_trace

from roboprobe.backends.base import (
    BackendCapabilities,
    EpisodeRequest,
    EpisodeResult,
    MaterializedScenario,
    assert_supports,
    episode_timeouts,
)
from roboprobe.backends.kinematic2d.backend import Kinematic2DBackend
from roboprobe.backends.replay.backend import ReplayBackend
from roboprobe.backends.trace_io import write_trace
from roboprobe.core import errors
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import NavStatus, SutProfile, Trace
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.task import load_task

pytestmark = pytest.mark.contract

REPO = Path(__file__).resolve().parents[3]
MIN_HZ = 10.0


class _Backend(Protocol):
    capabilities: BackendCapabilities

    def materialize(self, req: EpisodeRequest) -> MaterializedScenario: ...

    def run_episode(
        self, req: EpisodeRequest, materialized: MaterializedScenario, on_progress=None
    ) -> EpisodeResult: ...

    def cancel(self) -> None: ...


class FakeBackend:
    """In-memory backend used to self-test the contract suite."""

    def __init__(self, settings: RoboProbeSettings) -> None:
        """Store settings for timeout defaults (unused by the fake)."""
        self.capabilities = BackendCapabilities(
            name="fake",
            supported_params=frozenset({"robot.max_speed"}),
            deterministic=True,
            typical_episode_wall_s=0.01,
            max_parallel_per_host=8,
        )
        self._settings = settings

    def prepare(self) -> None:
        return None

    def materialize(self, req: EpisodeRequest) -> MaterializedScenario:
        req.workdir.mkdir(parents=True, exist_ok=True)
        world = req.workdir / "world.txt"
        world.write_text(req.scenario.scenario_hash, encoding="utf-8")
        return MaterializedScenario(
            files={"world": world}, payload={"hash": req.scenario.scenario_hash}
        )

    def run_episode(
        self, req: EpisodeRequest, materialized: MaterializedScenario, on_progress=None
    ) -> EpisodeResult:
        del on_progress, materialized
        trace = make_trace()
        path = req.workdir / "trace.parquet"
        write_trace(trace, path)
        return EpisodeResult(
            trace=trace, artifacts={"trace": path}, backend_meta={"backend": "fake"}
        )

    def cancel(self) -> None:
        return None

    def shutdown(self) -> None:
        return None


def _settings() -> RoboProbeSettings:
    return RoboProbeSettings(
        backends={
            "kinematic2d": {
                "model_file": str(REPO / "configs/backends/kinematic2d_v1.yaml"),
                "perception_model_file": str(REPO / "configs/perception/oakd_k2d_v1.yaml"),
            },
        }
    )


def _task():
    return load_task(REPO / "tasks" / "warehouse_delivery_v1.yaml", strict=False)


def _scenario():
    return ScenarioSpace.from_yaml(
        REPO / "configs" / "scenario_spaces" / "warehouse_v1.yaml", base_dir=REPO
    ).nominal()


def _request(tmp_path: Path, settings: RoboProbeSettings, *, seed: int = 1) -> EpisodeRequest:
    sim, wall = episode_timeouts(settings.worker)
    return EpisodeRequest(
        run_id=uuid4(),
        scenario=_scenario(),
        task=_task(),
        sut_profile=SutProfile(id="t", backend="kinematic2d", config={}, config_hash="c" * 16),
        seed=seed,
        workdir=tmp_path,
        sim_time_budget_s=min(sim, 30.0),
        wall_timeout_s=wall,
    )


@pytest.fixture(params=["fake", "replay", "kinematic2d"])
def backend_name(request: pytest.FixtureRequest) -> str:
    return str(request.param)


@pytest.fixture
def backend(backend_name: str, tmp_path: Path) -> _Backend:
    settings = _settings()
    if backend_name == "fake":
        return FakeBackend(settings)
    if backend_name == "kinematic2d":
        return Kinematic2DBackend(settings)
    source = tmp_path / "golden.parquet"
    write_trace(make_trace(), source)
    return ReplayBackend(settings, traces={})


def test_materialize_determinism(backend: _Backend, tmp_path: Path) -> None:
    if backend.capabilities.name == "replay":
        pytest.skip("replay materialize records a path, not generated world bytes")
    settings = _settings()
    a = _request(tmp_path / "a", settings)
    b = _request(tmp_path / "b", settings)
    ma, mb = backend.materialize(a), backend.materialize(b)
    for key in ma.files:
        assert ma.files[key].read_bytes() == mb.files[key].read_bytes()


def test_trace_schema_and_rate(backend: _Backend, tmp_path: Path) -> None:
    settings = _settings()
    req = _request(tmp_path / "r", settings)
    if backend.capabilities.name == "replay":
        source = tmp_path / "golden.parquet"
        write_trace(make_trace(), source)
        materialized = MaterializedScenario(files={"trace": source}, payload={})
    else:
        materialized = backend.materialize(req)
    result = backend.run_episode(req, materialized)
    assert result.infra_error is None
    trace = result.trace
    assert isinstance(trace, Trace)
    assert trace.n_samples >= 2
    rate = (trace.n_samples - 1) / trace.duration_s
    assert rate + 1e-9 >= MIN_HZ
    assert set(trace.nav_status).issubset({s.value for s in NavStatus})


def test_infra_errors_not_raised(backend: _Backend, tmp_path: Path) -> None:
    settings = _settings()
    req = _request(tmp_path, settings)
    if backend.capabilities.name != "replay":
        pytest.skip("infra path covered by replay missing file")
    materialized = MaterializedScenario(files={"trace": tmp_path / "missing.parquet"}, payload={})
    result = backend.run_episode(req, materialized)
    assert result.infra_error is not None


def test_supported_params_honesty(backend: _Backend) -> None:
    assert_supports(backend.capabilities, ["robot.max_speed"])
    if "env.not_a_param" not in backend.capabilities.supported_params:
        with pytest.raises(errors.ValidationError) as exc:
            assert_supports(backend.capabilities, ["env.not_a_param"])
        assert exc.value.code is errors.ErrorCode.BACKEND_UNSUPPORTED_PARAM


def test_cancel_is_safe(backend: _Backend) -> None:
    backend.cancel()
