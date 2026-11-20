"""NFR-PERF-001/002 propose and k2d episode latency gates (T-053)."""

from __future__ import annotations

import json
import os
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
import yaml
from pytest_benchmark.fixture import BenchmarkFixture
from tests.factories import make_observation

from roboprobe.backends.base import EpisodeRequest, episode_timeouts
from roboprobe.backends.kinematic2d.backend import Kinematic2DBackend
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import SutProfile, Verdict
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.task import load_task
from roboprobe.selection.base import StrategyContext
from roboprobe.selection.registry import create

pytestmark = [
    pytest.mark.benchmark,
    pytest.mark.filterwarnings("ignore:.*torch.jit.script.*:FutureWarning"),
]

HERE = Path(__file__).resolve().parent
REPO_ROOT = HERE.parents[2]
THRESHOLDS = yaml.safe_load((HERE / "thresholds.yaml").read_text(encoding="utf-8"))["perf"]
BASELINES = HERE / "baselines"


def _baseline(name: str) -> float:
    payload = json.loads((BASELINES / name).read_text(encoding="utf-8"))
    return float(payload["median_s"])


def _pin_threads() -> None:
    os.environ.setdefault("OMP_NUM_THREADS", "1")
    os.environ.setdefault("MKL_NUM_THREADS", "1")
    os.environ.setdefault("TORCH_NUM_THREADS", "1")


def _space(dim: int) -> ScenarioSpace:
    space = ScenarioSpace.from_yaml(
        REPO_ROOT / "configs" / "scenario_spaces" / "warehouse_v1.yaml",
        base_dir=REPO_ROOT,
    )
    if dim < space.dim:
        values = space.nominal_values()
        pins = {p.id: values[p.id] for p in space.params[dim:]}
        space = space.with_pins(pins)
    return space


def _k2d_settings() -> RoboProbeSettings:
    return RoboProbeSettings(
        backends={
            "kinematic2d": {
                "model_file": str(REPO_ROOT / "configs" / "backends" / "kinematic2d_v1.yaml")
            },
            "gazebo_nav2": {
                "perception_model_file": str(
                    REPO_ROOT / "configs" / "perception" / "oakd_lowlight_v1.yaml"
                )
            },
        }
    )


def test_propose_latency_against_baseline(benchmark: BenchmarkFixture) -> None:
    _pin_threads()
    dim = int(THRESHOLDS["propose_dim"])
    n = int(THRESHOLDS["propose_n"])
    q = int(THRESHOLDS["propose_q"])
    space = _space(dim)
    rng = np.random.default_rng(0)
    x = rng.random((n, dim))
    y = 0.2 - 0.5 * x[:, 0]
    history = [
        make_observation(
            x_unit=tuple(float(v) for v in row),
            robustness=float(rho),
            verdict=Verdict.FAIL if rho < 0.0 else Verdict.PASS,
        )
        for row, rho in zip(x, y, strict=True)
    ]
    strat = create(
        "S-PROBE",
        StrategyContext(space=space, budget=max(n + 20, 100), seed=0, batch_size=q, params={}),
    )

    def _call() -> int:
        return len(strat.propose(history, [], q))

    count = benchmark(_call)
    assert count == q
    if benchmark.stats is not None:
        median = float(benchmark.stats.stats.median)
        assert median <= float(THRESHOLDS["propose_hard_cap_s"])
        assert median <= _baseline("propose_n64_d8.json") * float(THRESHOLDS["regression_factor"])


def test_k2d_episode_against_baseline(benchmark: BenchmarkFixture, tmp_path: Path) -> None:
    _pin_threads()
    settings = _k2d_settings()
    backend = Kinematic2DBackend(settings)
    space = ScenarioSpace.from_yaml(
        REPO_ROOT / "configs" / "scenario_spaces" / "warehouse_v1.yaml",
        base_dir=REPO_ROOT,
    )
    sim, wall = episode_timeouts(settings.worker)
    req = EpisodeRequest(
        run_id=uuid4(),
        scenario=space.nominal(),
        task=load_task(REPO_ROOT / "tasks" / "warehouse_delivery_v1.yaml", strict=False),
        sut_profile=SutProfile(id="k2d", backend="kinematic2d", config={}, config_hash="a" * 16),
        seed=11,
        workdir=tmp_path / "run",
        sim_time_budget_s=min(sim, 30.0),
        wall_timeout_s=wall,
    )
    materialized = backend.materialize(req)

    def _call() -> object:
        return backend.run_episode(req, materialized)

    result = benchmark(_call)
    assert getattr(result, "infra_error", None) is None
    if benchmark.stats is not None:
        median = float(benchmark.stats.stats.median)
        assert median <= float(THRESHOLDS["k2d_hard_cap_s"])
        assert median <= _baseline("k2d_episode.json") * float(THRESHOLDS["regression_factor"])
