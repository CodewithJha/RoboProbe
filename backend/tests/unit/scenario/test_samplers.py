"""Tests for the unit-cube samplers (T-023; docs/05 §3, docs/07 §3)."""

from __future__ import annotations

import itertools
import math
from pathlib import Path

import numpy as np
import pytest
from scipy import stats

from roboprobe.core import errors
from roboprobe.core.types import ParamType
from roboprobe.scenario import samplers
from roboprobe.scenario.normalize import from_unit_batch
from roboprobe.scenario.space import ParameterSpec, PriorSpec, ScenarioSpace

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
WAREHOUSE = REPO_ROOT / "configs" / "scenario_spaces" / "warehouse_v1.yaml"
SEEDS = (0, 1, 2)
KS_ALPHA = 0.01
N_STAT = 4000
DIM = 4


def rng(seed: int = 0) -> np.random.Generator:
    return np.random.default_rng(seed)


def ks_uniform_ok(points: np.ndarray) -> bool:
    return all(
        stats.kstest(points[:, j], "uniform").pvalue > KS_ALPHA for j in range(points.shape[1])
    )


def float_param(
    prior: PriorSpec, *, low: float = 0.0, high: float = 1.0, scale: str = "linear"
) -> ParameterSpec:
    return ParameterSpec(
        id="robot.x", name="x", type=ParamType.FLOAT, unit="-", low=low, high=high, nominal=low,
        prior=prior, scale=scale, group="robot",  # type: ignore[arg-type]
    )  # fmt: skip


def int_param(prior: PriorSpec, *, low: int = 0, high: int = 4) -> ParameterSpec:
    return ParameterSpec(
        id="comms.n", name="n", type=ParamType.INT, unit="-", low=low, high=high, nominal=low,
        prior=prior, group="comms",
    )  # fmt: skip


def categorical_param(prior: PriorSpec) -> ParameterSpec:
    return ParameterSpec(
        id="env.c", name="c", type=ParamType.CATEGORICAL, unit="-", choices=("a", "b", "c"),
        nominal="a", prior=prior, group="environment",
    )  # fmt: skip


def decoded(param: ParameterSpec, n: int = N_STAT, seed: int = 0) -> np.ndarray:
    u = samplers.PriorSampler([param]).sample(n, rng(seed))
    return np.array([row[param.id] for row in from_unit_batch([param], u)])


# --------------------------------------------------------------------------- shared behaviour


@pytest.mark.parametrize("factory", [
    lambda: samplers.UniformSampler(DIM),
    lambda: samplers.LatinHypercubeSampler(DIM),
    lambda: samplers.SobolSampler(DIM),
    lambda: samplers.GridSampler(DIM, 3),
    lambda: samplers.PriorSampler([float_param(PriorSpec(kind="uniform"))] * DIM),
])  # fmt: skip
def test_shape_range_and_determinism(factory: object) -> None:
    make = factory  # type: ignore[assignment]
    first = make().sample(16, rng(7))  # type: ignore[operator]
    again = make().sample(16, rng(7))  # type: ignore[operator]
    assert first.shape == (16, DIM)
    assert first.dtype == np.float64
    assert np.all((first >= 0) & (first <= 1))
    np.testing.assert_array_equal(first, again)
    assert make().sample(0, rng()).shape == (0, DIM)  # type: ignore[operator]
    with pytest.raises(errors.ValidationError, match="negative"):
        make().sample(-1, rng())  # type: ignore[operator]


def test_sampler_protocol_is_structural() -> None:
    def draw(sampler: samplers.Sampler) -> np.ndarray:
        return sampler.sample(2, rng())

    assert draw(samplers.UniformSampler(2)).shape == (2, 2)


@pytest.mark.parametrize(
    "cls", [samplers.UniformSampler, samplers.LatinHypercubeSampler, samplers.SobolSampler]
)
def test_dimension_must_be_positive(cls: type) -> None:
    with pytest.raises(errors.ValidationError, match="dimension"):
        cls(0)


def test_prior_sampler_needs_parameters() -> None:
    with pytest.raises(errors.ValidationError, match="dimension"):
        samplers.PriorSampler([])


# --------------------------------------------------------------------------- marginal uniformity


@pytest.mark.parametrize("seed", SEEDS)
@pytest.mark.parametrize("make", [samplers.UniformSampler, samplers.LatinHypercubeSampler])
def test_marginals_are_uniform(make: type, seed: int) -> None:
    assert ks_uniform_ok(make(DIM).sample(N_STAT, rng(seed)))


@pytest.mark.parametrize("seed", SEEDS)
def test_sobol_marginals_are_uniform(seed: int) -> None:
    assert ks_uniform_ok(samplers.SobolSampler(DIM).sample(4096, rng(seed)))


# --------------------------------------------------------------------------- LHS


@pytest.mark.parametrize(("n", "seed"), [(1, 0), (10, 1), (37, 2), (200, 3)])
def test_lhs_has_one_point_per_stratum(n: int, seed: int) -> None:
    points = samplers.LatinHypercubeSampler(DIM).sample(n, rng(seed))
    for j in range(DIM):
        assert sorted(np.floor(points[:, j] * n).astype(int)) == list(range(n))


def test_lhs_without_optimisation() -> None:
    points = samplers.LatinHypercubeSampler(2, optimization=None).sample(8, rng())
    assert sorted(np.floor(points[:, 0] * 8).astype(int)) == list(range(8))


# --------------------------------------------------------------------------- Sobol


@pytest.mark.parametrize("m", [3, 6, 8])
def test_sobol_power_of_two_prefix_is_balanced(m: int) -> None:
    n = 2**m
    points = samplers.SobolSampler(DIM, seed=11).sample(n, rng())
    for j in range(DIM):
        assert sorted(np.floor(points[:, j] * n).astype(int)) == list(range(n))


def test_sobol_is_consumed_in_order_and_resumable() -> None:
    whole = samplers.SobolSampler(3, seed=5).sample(64, rng())
    sampler = samplers.SobolSampler(3, seed=5)
    parts = np.vstack(
        [sampler.sample(10, rng(99)), sampler.sample(22, rng(98)), sampler.sample(32, rng())]
    )
    np.testing.assert_array_equal(parts, whole)
    assert sampler.position == 64
    resumed = samplers.SobolSampler(3, seed=5).fast_forward(32)
    np.testing.assert_array_equal(resumed.sample(32, rng()), whole[32:])
    assert resumed.position == 64


def test_sobol_seed_is_derived_from_first_rng_only() -> None:
    a, b = samplers.SobolSampler(2), samplers.SobolSampler(2)
    assert a.seed is None
    first = a.sample(4, rng(3))
    assert a.seed is not None
    np.testing.assert_array_equal(first, b.sample(4, rng(3)))
    replay = samplers.SobolSampler(2, seed=a.seed)
    np.testing.assert_array_equal(replay.sample(4, rng(123)), first)
    assert not np.array_equal(samplers.SobolSampler(2).sample(4, rng(4)), first)


def test_sobol_non_power_of_two_does_not_warn() -> None:
    # pytest runs with filterwarnings=error, so a leaked SciPy warning would fail here
    samplers.SobolSampler(2, seed=1).sample(5, rng())


def test_sobol_fast_forward_needs_a_seed_source() -> None:
    with pytest.raises(errors.ValidationError, match="seed or an rng"):
        samplers.SobolSampler(2).fast_forward(4)
    assert samplers.SobolSampler(2).fast_forward(4, rng(1)).position == 4


def test_sobol_zero_points_still_seeds() -> None:
    sampler = samplers.SobolSampler(2)
    assert sampler.sample(0, rng(1)).shape == (0, 2)
    assert sampler.seed is not None
    assert sampler.position == 0


# --------------------------------------------------------------------------- grid


def test_grid_size_levels_and_lexicographic_order() -> None:
    grid = samplers.GridSampler(2, 3)
    assert grid.size == 9
    expected = np.array(list(itertools.product([0.0, 0.5, 1.0], repeat=2)))
    np.testing.assert_array_equal(grid.points(), expected)
    np.testing.assert_array_equal(grid.sample(9, rng()), expected)


def test_grid_subset_is_a_seeded_permutation_of_distinct_points() -> None:
    grid = samplers.GridSampler(3, 4)
    subset = grid.sample(20, rng(1))
    assert len({tuple(p) for p in subset}) == 20
    assert {tuple(p) for p in subset} <= {tuple(p) for p in grid.points()}
    np.testing.assert_array_equal(subset, grid.sample(20, rng(1)))


def test_huge_grid_subset_does_not_materialise_the_grid() -> None:
    grid = samplers.GridSampler(12, 10)  # 10**12 points
    subset = grid.sample(5, rng(2))
    assert subset.shape == (5, 12)
    assert set(np.unique(subset * 9).round(9)) <= set(range(10))


def test_grid_rejects_too_many_points_and_too_few_levels() -> None:
    with pytest.raises(errors.ValidationError, match="cannot draw"):
        samplers.GridSampler(2, 2).sample(5, rng())
    with pytest.raises(errors.ValidationError, match="levels"):
        samplers.GridSampler(2, 1)


@pytest.mark.parametrize(
    ("dim", "budget", "levels"),
    [
        (3, 1000, 10),
        (2, 100, 10),
        (2, 99, 9),
        (6, 30, 2),
        (6, 64, 2),
        (6, 729, 3),
        (1, 7, 7),
        (4, 0, 2),
        (2, 10**18 - 1, 999_999_999),  # float sqrt rounds up to 1e9 here
    ],
)
def test_grid_for_budget(dim: int, budget: int, levels: int) -> None:
    assert samplers.GridSampler.for_budget(dim, budget).levels == levels


# --------------------------------------------------------------------------- priors


def test_uniform_prior_on_linear_float_is_uniform_in_unit_space() -> None:
    u = samplers.PriorSampler([float_param(PriorSpec(kind="uniform"))]).sample(N_STAT, rng())
    assert ks_uniform_ok(u)


def test_loguniform_prior_on_log_scale_is_uniform_in_unit_space() -> None:
    lux = float_param(PriorSpec(kind="loguniform"), low=5, high=1000, scale="log")
    u = samplers.PriorSampler([lux]).sample(N_STAT, rng())
    assert ks_uniform_ok(u)
    values = decoded(lux)
    assert stats.kstest(values, stats.loguniform(5, 1000).cdf).pvalue > KS_ALPHA


def test_uniform_prior_on_log_scale_is_uniform_in_values() -> None:
    param = float_param(PriorSpec(kind="uniform"), low=5, high=1000, scale="log")
    values = decoded(param)
    assert stats.kstest(values, stats.uniform(5, 995).cdf).pvalue > KS_ALPHA
    u = samplers.PriorSampler([param]).sample(N_STAT, rng())
    assert np.median(u) > 0.5 + 0.3  # most mass sits at large values, i.e. near u = 1


def test_loguniform_prior_on_linear_scale() -> None:
    values = decoded(float_param(PriorSpec(kind="loguniform"), low=1, high=100))
    assert stats.kstest(values, stats.loguniform(1, 100).cdf).pvalue > KS_ALPHA


def test_truncnormal_prior() -> None:
    values = decoded(float_param(PriorSpec(kind="truncnormal", mean=0.2, std=0.3)))
    expected = stats.truncnorm((0 - 0.2) / 0.3, (1 - 0.2) / 0.3, loc=0.2, scale=0.3)
    assert stats.kstest(values, expected.cdf).pvalue > KS_ALPHA
    assert values.min() >= 0
    assert values.max() <= 1


def test_beta_prior_spans_the_range() -> None:
    values = decoded(float_param(PriorSpec(kind="beta", a=2, b=5), low=10, high=20))
    assert stats.kstest(values, stats.beta(2, 5, loc=10, scale=10).cdf).pvalue > KS_ALPHA


def chi_square_ok(values: np.ndarray, levels: list[object], probabilities: list[float]) -> bool:
    observed = np.array([np.sum(values == level) for level in levels])
    expected = np.array(probabilities) * len(values)
    mask = expected > 0
    assert np.all(observed[~mask] == 0)
    return bool(stats.chisquare(observed[mask], expected[mask]).pvalue > KS_ALPHA)


def test_int_uniform_prior_gives_equal_levels() -> None:
    assert chi_square_ok(decoded(int_param(PriorSpec(kind="uniform"))), [0, 1, 2, 3, 4], [0.2] * 5)


def test_int_continuous_prior_gives_each_integer_its_interval_mass() -> None:
    prior = PriorSpec(kind="truncnormal", mean=0.0, std=1.0)
    dist = stats.truncnorm(-0.5, 4.5, loc=0, scale=1)
    probabilities = [float(dist.cdf(k + 0.5) - dist.cdf(k - 0.5)) for k in range(5)]
    assert chi_square_ok(decoded(int_param(prior)), [0, 1, 2, 3, 4], probabilities)


def test_int_loguniform_prior() -> None:
    dist = stats.loguniform(0.5, 4.5)
    probabilities = [float(dist.cdf(k + 0.5) - dist.cdf(k - 0.5)) for k in range(1, 5)]
    values = decoded(int_param(PriorSpec(kind="loguniform"), low=1, high=4))
    assert chi_square_ok(values, [1, 2, 3, 4], probabilities)


def test_discrete_int_prior_with_zero_weights() -> None:
    values = decoded(int_param(PriorSpec(kind="discrete", weights=(1, 0, 3, 0, 0))))
    assert chi_square_ok(values, [0, 1, 2, 3, 4], [0.25, 0, 0.75, 0, 0])


def test_discrete_categorical_prior() -> None:
    values = decoded(categorical_param(PriorSpec(kind="discrete", weights=(0.5, 0.25, 0.25))))
    assert chi_square_ok(values, ["a", "b", "c"], [0.5, 0.25, 0.25])


def test_uniform_categorical_prior() -> None:
    values = decoded(categorical_param(PriorSpec(kind="uniform")))
    assert chi_square_ok(values, ["a", "b", "c"], [1 / 3] * 3)


def test_discrete_points_land_inside_their_bin() -> None:
    param = categorical_param(PriorSpec(kind="discrete", weights=(0, 1, 0)))
    u = samplers.PriorSampler([param]).sample(500, rng())
    assert np.all((u >= 1 / 3) & (u <= 2 / 3))
    assert stats.kstest((u[:, 0] - 1 / 3) * 3, "uniform").pvalue > KS_ALPHA


def test_prior_sampler_over_the_warehouse_space() -> None:
    space = ScenarioSpace.from_yaml(WAREHOUSE, base_dir=REPO_ROOT)
    u = samplers.PriorSampler(space.params).sample(N_STAT, rng())
    assert u.shape == (N_STAT, space.dim)
    assert ks_uniform_ok(u)  # every warehouse prior matches its scale (P3: loguniform + log)
    values = space.from_unit_batch(u[:5])
    assert all(set(row) == {p.id for p in space.params} for row in values)
    assert math.isfinite(float(values[0]["env.illuminance"]))
