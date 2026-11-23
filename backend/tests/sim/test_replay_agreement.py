"""Check same-seed Gazebo agreement for a canonical warehouse failure (T-098)."""

from pathlib import Path

import pytest
from tests.sim._warehouse_acceptance import load_warehouse, run_warehouse

from roboprobe.core.types import FailureClass, Verdict
from roboprobe.metrics import Replay, reproducibility

pytestmark = pytest.mark.sim

_CANONICAL_SEED = 1
_CANONICAL_PROFILE = "tb4_nav2_ack_1000ms"
_CANONICAL_MODE = "warehouse_collision"
_REPLAY_COUNT = 5  # MET-06, docs/19 §3
_MIN_AGREEMENT = 0.8  # SC-5, docs/19 §6


@pytest.mark.timeout(3600)
def test_gazebo_same_seed_replays_match_canonical_failure(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    """Judge a real source episode and five repeats with the production oracles."""
    space = load_warehouse(request)
    scenario = space.make_scenario({"obstacle.clearance": 0.0, "env.illuminance": 5.0})
    source = run_warehouse(
        space,
        scenario,
        _CANONICAL_SEED,
        tmp_path / "source",
        profile_id=_CANONICAL_PROFILE,
    )
    assert source.result.infra_error is None, source.result.infra_error
    original = Replay(source.outcome.verdict, source.outcome.primary_failure)
    assert original == Replay(Verdict.FAIL, FailureClass.COL)

    replays: list[Replay] = []
    for index in range(_REPLAY_COUNT):
        trial = run_warehouse(
            space,
            scenario,
            _CANONICAL_SEED,
            tmp_path / f"replay-{index + 1}",
            profile_id=_CANONICAL_PROFILE,
        )
        assert trial.result.infra_error is None, (index + 1, trial.result.infra_error)
        replays.append(Replay(trial.outcome.verdict, trial.outcome.primary_failure))

    agreement = reproducibility({_CANONICAL_MODE: original}, {_CANONICAL_MODE: replays})
    assert agreement >= _MIN_AGREEMENT, (agreement, original, replays)
