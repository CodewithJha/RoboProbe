"""Require the dark, on-path pallet to cause the canonical Gazebo collision (T-098)."""

from pathlib import Path

import pytest
from tests.sim._warehouse_acceptance import load_warehouse, run_warehouse

from roboprobe.core.types import FailureClass, Verdict

pytestmark = pytest.mark.sim


@pytest.mark.timeout(600)
def test_canonical_on_path_pallet_in_low_light_fails_with_collision(
    request: pytest.FixtureRequest, tmp_path: Path
) -> None:
    space = load_warehouse(request)
    scenario = space.make_scenario({"obstacle.clearance": 0.0, "env.illuminance": 5.0})
    trial = run_warehouse(
        space,
        scenario,
        1,
        tmp_path / "canonical",
        profile_id="tb4_nav2_ack_1000ms",
        record_bag=True,
    )
    infra_error = trial.result.infra_error
    assert infra_error is None
    observed = (trial.outcome.verdict, trial.outcome.primary_failure)
    assert observed == (Verdict.FAIL, FailureClass.COL)
    assert trial.result.trace.contact.any()
