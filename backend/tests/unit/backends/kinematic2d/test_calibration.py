"""kinematic2d GT calibration acceptance (T-034, docs/18 §4.7)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest

from roboprobe.backends.base import EpisodeRequest, episode_timeouts
from roboprobe.backends.kinematic2d.backend import Kinematic2DBackend
from roboprobe.backends.kinematic2d.calibration import load_calibration
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import SutProfile, Verdict
from roboprobe.oracles.registry import create_all
from roboprobe.oracles.verdict import VerdictEngine
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.task import load_task
from tests.factories import make_scenario

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]


def _settings() -> RoboProbeSettings:
    root = REPO
    return RoboProbeSettings(
        backends={
            "kinematic2d": {
                "model_file": str(root / "configs/backends/kinematic2d_v1.yaml"),
                "perception_model_file": str(root / "configs/perception/oakd_k2d_v1.yaml"),
                "calibration_file": str(root / "configs/reference/k2d_gt_canonical.yaml"),
            }
        }
    )


@pytest.fixture()
def harness(tmp_path: Path):
    settings = _settings()
    cal = load_calibration(Path(settings.backends.kinematic2d.calibration_file))
    space = ScenarioSpace.from_yaml(
        REPO / "configs/scenario_spaces/warehouse_v1.yaml", base_dir=REPO
    )
    task = load_task(REPO / "tasks/warehouse_delivery_v1.yaml", strict=False)
    backend = Kinematic2DBackend(settings)
    engine = VerdictEngine(create_all(settings.oracles))
    sim, wall = episode_timeouts(settings.worker)

    def run(u: tuple[float, ...]) -> Verdict:
        scenario = make_scenario(values=space.from_unit(u))
        req = EpisodeRequest(
            run_id=uuid4(),
            scenario=scenario,
            task=task,
            sut_profile=SutProfile(
                id="k2d", backend="kinematic2d", config={}, config_hash="c" * 16
            ),
            seed=0,
            workdir=tmp_path / "work",
            sim_time_budget_s=sim,
            wall_timeout_s=wall,
        )
        materialized = backend.materialize(req)
        outcome = engine.judge(backend.run_episode(req, materialized), task)
        return outcome.verdict

    return cal, run


def test_canonical_modes_fail_and_nominal_passes(harness) -> None:
    """Each designed GT scenario fails; nominal passes (FR-SIM-002)."""
    cal, run = harness
    assert run(cal.nominal_unit) == Verdict.PASS
    for label, unit in cal.mode_points():
        verdict = run(unit)
        assert verdict == Verdict.FAIL, label