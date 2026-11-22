"""Unit tests for RiskMapper (T-076)."""

from __future__ import annotations

import time
from pathlib import Path

import numpy as np
import pytest
from scipy.stats import norm

from roboprobe.core.settings.analysis import RiskThresholds
from roboprobe.risk.mapper import (
    REGION_FAILURE,
    REGION_SAFE,
    REGION_UNCERTAIN,
    RiskMapper,
    load_slices,
    save_slices,
)
from roboprobe.scenario.space import ScenarioSpace

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[4]
BRANIN = REPO / "configs" / "scenario_spaces" / "branin_2d.yaml"
MULTI = REPO / "configs" / "scenario_spaces" / "multi_mode_6d.yaml"
WAREHOUSE = REPO / "configs" / "scenario_spaces" / "warehouse_v1.yaml"


class _StubGP:
    """Analytic mean/std so classification is exact."""

    def __init__(self, *, noise: float = 0.0) -> None:
        self._noise = noise

    def predict(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
        x_arr = np.asarray(x, dtype=np.float64)
        # Mean rises as the first free coord falls; std is constant.
        mean = 2.0 * (0.5 - x_arr[:, 0])
        std = np.full(x_arr.shape[0], 0.5, dtype=np.float64)
        return mean, std

    def predict_total_std(self, x: np.ndarray) -> np.ndarray:
        _, std = self.predict(x)
        return np.sqrt(std**2 + self._noise**2)


@pytest.fixture(scope="module")
def branin() -> ScenarioSpace:
    return ScenarioSpace.from_yaml(BRANIN, base_dir=REPO)


@pytest.fixture(scope="module")
def warehouse() -> ScenarioSpace:
    return ScenarioSpace.from_yaml(WAREHOUSE, base_dir=REPO)


def test_slice_shapes_and_classification(branin: ScenarioSpace) -> None:
    thresholds = RiskThresholds(safe=0.05, failure=0.95)
    mapper = RiskMapper(_StubGP(), branin, thresholds)
    anchor = branin.nominal_values()
    sl = mapper.slice("robot.u1", "robot.u2", anchor, resolution=5)
    assert sl.p_fail.shape == (5, 5)
    assert sl.mean.shape == (5, 5)
    assert sl.std.shape == (5, 5)
    assert sl.region.shape == (5, 5)
    assert sl.grid_u.shape == (5, 5, 2)
    assert sl.x_values.shape == (5,)
    assert not sl.log_x and not sl.log_y
    assert sl.region[0, 0] == REGION_SAFE
    assert REGION_FAILURE in {sl.region[0, -1], sl.region[-1, -1]}


def test_classify_codes(branin: ScenarioSpace) -> None:
    thresholds = RiskThresholds(safe=0.2, failure=0.8)
    mapper = RiskMapper(_StubGP(noise=0.0), branin, thresholds)
    sigma = 0.5
    targets = np.array([0.1, 0.5, 0.9])
    means = -sigma * norm.ppf(targets)
    u0 = (1.0 - means) / 2.0
    x = np.column_stack([u0, np.full(3, 0.5)])
    codes = mapper.classify(x)
    assert codes.tolist() == [int(REGION_SAFE), int(REGION_UNCERTAIN), int(REGION_FAILURE)]


def test_batches_realistic_atlas_queries_without_reordering(warehouse: ScenarioSpace) -> None:
    class LimitedGP(_StubGP):
        def predict(self, x: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
            assert 0 < len(x) <= 512
            return super().predict(x)

    gp = LimitedGP(noise=0.25)
    mapper = RiskMapper(gp, warehouse, RiskThresholds())
    predict = _StubGP(noise=0.25)
    for risk_slice in mapper.all_pair_slices(warehouse.nominal_values()):
        points = risk_slice.grid_u.reshape(-1, warehouse.dim)
        mean, latent_std = predict.predict(points)
        total_std = predict.predict_total_std(points)
        np.testing.assert_allclose(risk_slice.mean.ravel(), mean)
        np.testing.assert_allclose(risk_slice.std.ravel(), latent_std)
        np.testing.assert_allclose(risk_slice.p_fail.ravel(), norm.cdf(-mean / total_std))
        np.testing.assert_array_equal(mapper.classify(points), risk_slice.region.ravel())


def test_pins_respected(warehouse: ScenarioSpace) -> None:
    pinned = warehouse.with_pins({"env.illuminance": 50.0})
    assert pinned.dim == warehouse.dim - 1
    assert "env.illuminance" not in {p.id for p in pinned.params}
    thresholds = RiskThresholds()
    mapper = RiskMapper(_StubGP(), pinned, thresholds)
    free = [p.id for p in pinned.params]
    sl = mapper.slice(free[0], free[1], pinned.nominal_values(), resolution=3)
    assert sl.grid_u.shape == (3, 3, pinned.dim)


def test_log_axis_flag(warehouse: ScenarioSpace) -> None:
    lux = warehouse.param("env.illuminance")
    assert lux.scale == "log"
    other = next(p.id for p in warehouse.params if p.id != "env.illuminance")
    mapper = RiskMapper(_StubGP(), warehouse, RiskThresholds())
    sl = mapper.slice("env.illuminance", other, warehouse.nominal_values(), resolution=4)
    assert sl.log_x is True
    assert sl.x_values[0] > 0
    ratios = sl.x_values[1:] / sl.x_values[:-1]
    assert np.allclose(ratios, ratios[0], rtol=1e-5)


def test_npz_roundtrip(branin: ScenarioSpace, tmp_path: Path) -> None:
    mapper = RiskMapper(_StubGP(), branin, RiskThresholds())
    slices = mapper.all_pair_slices(branin.nominal_values(), resolution=4)
    path = tmp_path / "slices.npz"
    save_slices(path, slices)
    loaded = load_slices(path)
    assert len(loaded) == len(slices) == 1
    a, b = slices[0], loaded[0]
    assert a.x_param == b.x_param and a.y_param == b.y_param
    np.testing.assert_array_equal(a.region, b.region)
    np.testing.assert_allclose(a.p_fail, b.p_fail)
    np.testing.assert_allclose(a.grid_u, b.grid_u)


@pytest.mark.benchmark
def test_all_pair_slices_six_d_under_one_second() -> None:
    space = ScenarioSpace.from_yaml(MULTI, base_dir=REPO)
    assert space.dim == 6
    mapper = RiskMapper(_StubGP(), space, RiskThresholds())
    started = time.perf_counter()
    slices = mapper.all_pair_slices(space.nominal_values(), resolution=50)
    elapsed = time.perf_counter() - started
    assert len(slices) == 15
    assert elapsed < 1.0
