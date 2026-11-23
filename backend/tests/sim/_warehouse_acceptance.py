"""Run the production Gazebo warehouse profile and judge its real trace (T-098)."""

from __future__ import annotations

import json
import shutil
from dataclasses import dataclass
from pathlib import Path
from typing import cast
from uuid import uuid4

import pytest

from roboprobe.backends.base import EpisodeRequest, EpisodeResult
from roboprobe.backends.gazebo_nav2.backend import GazeboNav2Backend
from roboprobe.core.settings import load_settings
from roboprobe.core.types import JsonValue, RunOutcome, Scenario
from roboprobe.oracles.registry import create_all
from roboprobe.oracles.verdict import EpisodeView, VerdictEngine
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.sut_profile import load_sut_profile

_REPO = Path(__file__).resolve().parents[3]
_SPACE = _REPO / "configs/scenario_spaces/warehouse_v1.yaml"
_PROFILES = _REPO / "configs/sut_profiles"


@dataclass(frozen=True, slots=True)
class JudgedWarehouseEpisode:
    """Preserve simulator telemetry and the production oracle verdict."""

    result: EpisodeResult
    outcome: RunOutcome


def load_warehouse(request: pytest.FixtureRequest) -> ScenarioSpace:
    """Load the shipped warehouse when the real Jazzy suite was selected."""
    if request.config.getoption("--backend") != "gazebo_nav2" or shutil.which("ros2") is None:
        pytest.skip("requires the installed Jazzy worker and --backend gazebo_nav2")
    return ScenarioSpace.from_yaml(_SPACE, base_dir=_REPO, strict_task=True)


def run_warehouse(  # noqa: PLR0913 - explicit scenario, reproducibility and artifact inputs
    space: ScenarioSpace,
    scenario: Scenario,
    seed: int,
    workdir: Path,
    *,
    profile_id: str = "tb4_nav2_default",
    record_bag: bool = False,
) -> JudgedWarehouseEpisode:
    """Execute and persist evidence for one real Gazebo episode."""
    settings = load_settings(
        {"worker.backend": "gazebo_nav2", "storage.workdir_root": workdir.parent}
    )
    backend = GazeboNav2Backend(settings)
    episode = EpisodeRequest(
        run_id=uuid4(),
        scenario=scenario,
        task=space.task,
        sut_profile=load_sut_profile(_PROFILES / f"{profile_id}.yaml", strict=True),
        seed=seed,
        workdir=workdir,
        sim_time_budget_s=settings.worker.default_sim_time_budget_s,
        wall_timeout_s=settings.worker.default_wall_timeout_s,
        record_bag=record_bag,
    )
    backend.prepare()
    try:
        result = backend.run_episode(episode, backend.materialize(episode))
    finally:
        backend.shutdown()

    outcome = VerdictEngine(create_all(settings.oracles)).judge(
        cast("EpisodeView", result), space.task
    )
    evidence: dict[str, JsonValue] = {
        "seed": seed,
        "sut_profile": profile_id,
        "scenario": dict(scenario.values),
        "backend": dict(result.backend_meta),
        "infra_error": result.infra_error,
        "outcome": outcome.model_dump(mode="json"),
    }
    (workdir / "acceptance.json").write_text(json.dumps(evidence, indent=2), encoding="utf-8")
    return JudgedWarehouseEpisode(result, outcome)
