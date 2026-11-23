"""Require the nominal warehouse episode to pass in at least four of five trials (T-098)."""

from pathlib import Path

import pytest
from tests.sim._warehouse_acceptance import load_warehouse, run_warehouse

from roboprobe.core.types import Verdict

pytestmark = pytest.mark.sim
_NOMINAL_SEEDS = (1, 2, 3, 4, 5)
_MINIMUM_PASSES = 4


@pytest.mark.timeout(2400)
def test_nominal_warehouse_passes_at_least_four_of_five(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    """Judge five seeded real episodes with the unchanged production oracles."""
    space = load_warehouse(request)
    scenario = space.nominal()
    trials = [
        run_warehouse(
            space,
            scenario,
            seed,
            tmp_path / f"nominal-{seed}",
            profile_id="tb4_nav2_warehouse_acceptance",
        )
        for seed in _NOMINAL_SEEDS
    ]
    assert sum(trial.outcome.verdict is Verdict.PASS for trial in trials) >= _MINIMUM_PASSES, [
        (seed, trial.outcome.verdict, trial.outcome.primary_failure, trial.result.backend_meta)
        for seed, trial in zip(_NOMINAL_SEEDS, trials, strict=True)
    ]
