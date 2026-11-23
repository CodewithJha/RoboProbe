"""Verify every warehouse parameter changes launch inputs in the installed image."""

from __future__ import annotations

import shutil
from pathlib import Path

import pytest
from tests.contract.test_backend_contract import REPO, _request

from roboprobe.backends.gazebo_nav2.backend import GazeboNav2Backend
from roboprobe.core.settings import load_settings
from roboprobe.scenario.space import ScenarioSpace

pytestmark = pytest.mark.sim


@pytest.mark.parametrize(
    ("parameter", "changed"),
    [
        ("robot.max_speed", {"nav2_params.yaml"}),
        ("obstacle.clearance", {"world.sdf", "episode.yaml"}),
        ("env.illuminance", {"world.sdf", "perturb_params.yaml"}),
        ("sensor.lidar_noise_std", {"perturb_params.yaml"}),
        ("env.floor_friction", {"world.sdf"}),
        ("comms.cmd_delay_ms", {"perturb_params.yaml"}),
        ("obstacle.along_path", {"world.sdf", "episode.yaml"}),
        ("sensor.lidar_dropout", {"perturb_params.yaml"}),
    ],
)
def test_each_parameter_changes_materialized_files(
    request: pytest.FixtureRequest, tmp_path: Path, parameter: str, changed: set[str]
) -> None:
    if request.config.getoption("--backend") != "gazebo_nav2" or shutil.which("ros2") is None:
        pytest.skip("requires the sourced Jazzy worker image and --backend gazebo_nav2")

    settings = load_settings()
    space = ScenarioSpace.from_yaml(
        REPO / "configs/scenario_spaces/warehouse_v1_d8.yaml", base_dir=REPO, strict_task=True
    )
    spec = next(spec for spec in space.params if spec.id == parameter)
    value = spec.low if spec.low != spec.nominal else spec.high
    episode = _request(tmp_path / "nominal", settings, backend_name="gazebo_nav2").model_copy(
        update={"scenario": space.nominal(), "task": space.task},
    )
    variant = episode.model_copy(
        update={
            "scenario": space.make_scenario({parameter: value}),
            "workdir": tmp_path / "varied",
        },
    )
    backend = GazeboNav2Backend(settings)
    before = backend.materialize(episode)
    after = backend.materialize(variant)
    assert before.files.keys() == after.files.keys()
    assert {
        name
        for name, path in before.files.items()
        if path.read_bytes() != after.files[name].read_bytes()
    } == changed
