"""kinematic2d episode loop (T-033d)."""

from __future__ import annotations

import hashlib
import time
from pathlib import Path

import numpy as np
import pytest

from roboprobe.backends.kinematic2d.episode import run_k2d_episode
from roboprobe.backends.kinematic2d.model import Kinematic2DModel
from roboprobe.backends.kinematic2d.world import load_world, nominal_path_polyline
from roboprobe.core.settings.backends import Kinematic2DSettings
from roboprobe.core.types import NavStatus
from roboprobe.perturbation.perception import PerceptionModel
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.task import load_task

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
MODEL = Kinematic2DModel.from_yaml(REPO / "configs" / "backends" / "kinematic2d_v1.yaml")
PERCEPTION = PerceptionModel.from_yaml(REPO / "configs" / "perception" / "oakd_lowlight_v1.yaml")
WALL_BUDGET_S = 2.0
SEED = 7


def _run(seed: int = SEED):
    space = ScenarioSpace.from_yaml(
        REPO / "configs" / "scenario_spaces" / "warehouse_v1.yaml", base_dir=REPO
    )
    scenario = space.nominal()
    task = load_task(REPO / "tasks" / "warehouse_delivery_v1.yaml", strict=False)
    world = load_world(REPO / "configs" / "backends" / "warehouse_k2d.json")
    return run_k2d_episode(
        world,
        task,
        scenario.values,
        MODEL,
        Kinematic2DSettings(),
        seed,
        perception=PERCEPTION,
        path=nominal_path_polyline(MODEL.world),
        sim_time_budget_s=120.0,
    )


def _digest(trace) -> str:
    h = hashlib.sha256()
    for name in ("t", "gt_x", "gt_y", "gt_yaw", "est_x", "cmd_v"):
        h.update(np.asarray(getattr(trace, name)).tobytes())
    return h.hexdigest()


def test_nominal_reaches_goal() -> None:
    trace = _run()
    assert trace.nav_status[-1] == NavStatus.SUCCEEDED
    assert trace.n_samples >= 2


def test_trace_hash_identical_for_equal_seed() -> None:
    assert _digest(_run()) == _digest(_run())


def test_episode_wall_time_budget() -> None:
    t0 = time.perf_counter()
    _run()
    assert time.perf_counter() - t0 <= WALL_BUDGET_S
