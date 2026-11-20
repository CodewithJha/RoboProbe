"""Analytic benchmarks and BenchmarkBackend (T-052, docs/07 §9)."""

from __future__ import annotations

import math
from pathlib import Path
from uuid import uuid4

import numpy as np
import pytest
from scipy.stats import qmc
from tests.factories import make_scenario

from roboprobe.backends.base import EpisodeRequest, episode_timeouts
from roboprobe.backends.benchmark.backend import (
    BRANIN_PARAM_ORDER,
    MULTI_MODE_PARAM_ORDER,
    BenchmarkBackend,
)
from roboprobe.core.seeding import SIMULATOR, make_rng
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import SutProfile
from roboprobe.scenario.task import load_task
from roboprobe.selection.benchmarks import (
    MODE_CANONICAL,
    NOMINAL_POINT,
    branin_falsify,
    label_mode,
    multi_mode_6d,
)

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[4]
_BRANIN_MINIMA = (
    (-math.pi, 12.275),
    (math.pi, 2.275),
    (9.42478, 2.475),
)


def test_multi_mode_failure_volume_matches_target() -> None:
    cfg = RoboProbeSettings().selection.benchmarks
    n = 1 << cfg.volume_qmc_power
    engine = qmc.Sobol(d=6, scramble=True, seed=0)
    unit = engine.random(n)
    fail = np.array(
        [multi_mode_6d(row, noise=0.0) < 0.0 for row in unit],
        dtype=np.bool_,
    )
    volume = float(np.mean(fail))
    assert abs(volume - cfg.failure_volume_target) <= cfg.failure_volume_atol


def test_canonical_modes_fail_and_nominal_passes() -> None:
    for mode, point in MODE_CANONICAL.items():
        rho = multi_mode_6d(point, noise=0.0)
        assert rho < 0.0, mode
        assert label_mode(point) == mode
    assert multi_mode_6d(NOMINAL_POINT, noise=0.0) > 0.0
    assert label_mode(NOMINAL_POINT) is None


def test_branin_minima_fail_and_centre_passes() -> None:
    for x1, x2 in _BRANIN_MINIMA:
        unit = ((x1 + 5.0) / 15.0, x2 / 15.0)
        assert branin_falsify(unit) < 0.0
    assert branin_falsify((0.5, 0.5)) > 0.0


def test_multi_mode_noise_uses_injected_rng() -> None:
    point = MODE_CANONICAL["D"]
    a = multi_mode_6d(point, noise=0.02, rng=make_rng(7, SIMULATOR))
    b = multi_mode_6d(point, noise=0.02, rng=make_rng(7, SIMULATOR))
    c = multi_mode_6d(point, noise=0.02, rng=make_rng(8, SIMULATOR))
    assert a == b
    assert a != c


def test_benchmark_backend_direct_rho_branin(tmp_path: Path) -> None:
    settings = RoboProbeSettings()
    settings = settings.model_copy(
        update={
            "selection": settings.selection.model_copy(
                update={
                    "benchmarks": settings.selection.benchmarks.model_copy(
                        update={"function": "branin_falsify", "noise": 0.0}
                    )
                }
            )
        }
    )
    backend = BenchmarkBackend(settings)
    assert backend.capabilities.direct_rho is True
    assert backend.capabilities.name == "benchmark"
    unit = ((-math.pi + 5.0) / 15.0, 12.275 / 15.0)
    values = {pid: float(v) for pid, v in zip(BRANIN_PARAM_ORDER, unit, strict=True)}
    result = _run(backend, settings, tmp_path, values, seed=0)
    assert result.infra_error is None
    rho = float(result.backend_meta["rho"])
    assert rho == pytest.approx(branin_falsify(unit))
    assert result.trace.meta["rho"] == pytest.approx(rho)


def test_benchmark_backend_direct_rho_multi_mode(tmp_path: Path) -> None:
    settings = RoboProbeSettings()
    settings = settings.model_copy(
        update={
            "selection": settings.selection.model_copy(
                update={
                    "benchmarks": settings.selection.benchmarks.model_copy(
                        update={"function": "multi_mode_6d", "noise": 0.0}
                    )
                }
            )
        }
    )
    backend = BenchmarkBackend(settings)
    values = {
        pid: float(v) for pid, v in zip(MULTI_MODE_PARAM_ORDER, MODE_CANONICAL["B"], strict=True)
    }
    result = _run(backend, settings, tmp_path, values, seed=3)
    assert result.infra_error is None
    rho = float(result.backend_meta["rho"])
    assert rho == pytest.approx(multi_mode_6d(MODE_CANONICAL["B"], noise=0.0))
    assert rho < 0.0


def _run(
    backend: BenchmarkBackend,
    settings: RoboProbeSettings,
    tmp_path: Path,
    values: dict[str, float],
    *,
    seed: int,
):
    sim, wall = episode_timeouts(settings.worker)
    req = EpisodeRequest(
        run_id=uuid4(),
        scenario=make_scenario(values=values),
        task=load_task(REPO / "tasks" / "warehouse_delivery_v1.yaml", strict=False),
        sut_profile=SutProfile(id="bench", backend="benchmark", config={}, config_hash="b" * 16),
        seed=seed,
        workdir=tmp_path / "work",
        sim_time_budget_s=sim,
        wall_timeout_s=wall,
    )
    materialized = backend.materialize(req)
    return backend.run_episode(req, materialized)
