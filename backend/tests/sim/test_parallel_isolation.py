"""Run two real warehouse episodes and compare their ROS graphs and distance traces."""

from __future__ import annotations

import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor
from contextlib import ExitStack
from pathlib import Path
from queue import Queue
from threading import Barrier
from time import monotonic
from typing import TYPE_CHECKING
from uuid import uuid4

import numpy as np
import pytest

from roboprobe.backends.base import EpisodeRequest, EpisodeResult
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.sut_profile import load_sut_profile

if TYPE_CHECKING:
    from roboprobe.backends.gazebo_nav2.backend import GazeboNav2Backend

pytestmark = pytest.mark.sim
_REPO = Path(__file__).resolve().parents[3]
_PROBES = ("/warehouse_isolation_near", "/warehouse_isolation_far")


def _node_graph(ros2: str, env: dict[str, str]) -> set[str]:
    observed = subprocess.run(  # noqa: S603 - executable resolved from the installed Jazzy environment
        [ros2, "node", "list", "--no-daemon", "--spin-time", "2.0"],
        env=env,
        capture_output=True,
        text=True,
        check=True,
        timeout=15.0,
    )
    return set(observed.stdout.splitlines())


def _assert_separate_graphs(ros2: str, environments: tuple[dict[str, str], dict[str, str]]) -> None:
    deadline = monotonic() + 150.0
    while monotonic() < deadline:
        graphs = [_node_graph(ros2, env) for env in environments]
        if all("/episode_manager" in graph for graph in graphs):
            for index, graph in enumerate(graphs):
                assert _PROBES[index] in graph
                assert _PROBES[1 - index] not in graph
            return
    pytest.fail("The two live episode managers did not become visible in their own ROS domains")


def test_two_parallel_warehouse_episodes_are_isolated(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ros2 = shutil.which("ros2")
    if ros2 is None:
        pytest.skip("The installed Jazzy simulator environment is required")
    rclpy = pytest.importorskip("rclpy")
    from roboprobe.backends.gazebo_nav2.backend import GazeboNav2Backend  # noqa: PLC0415
    from roboprobe.backends.gazebo_nav2.process import EpisodeProcess  # noqa: PLC0415

    monkeypatch.setenv("ROS_AUTOMATIC_DISCOVERY_RANGE", "LOCALHOST")
    settings = RoboProbeSettings.model_validate(
        {
            "worker": {"backend": "gazebo_nav2", "concurrency": 2},
            "storage": {"workdir_root": tmp_path},
            "backends": {"gazebo_nav2": {"max_parallel_per_host": 2, "startup_timeout_s": 150.0}},
        }
    )
    space = ScenarioSpace.from_yaml(
        _REPO / "configs/scenario_spaces/warehouse_v1.yaml", base_dir=_REPO
    )
    profile = load_sut_profile(_REPO / "configs/sut_profiles/tb4_nav2_default.yaml", strict=True)
    launch_environments: Queue[tuple[Path, dict[str, str]]] = Queue()
    paired = Barrier(2, timeout=30.0)
    run_process = EpisodeProcess.run

    def watch(  # noqa: PLR0913 - mirrors EpisodeProcess.run
        process, command, *, workdir, env, wall_timeout_s, cancel, on_progress=None
    ):
        launch_environments.put((workdir, dict(env)))
        paired.wait()
        return run_process(
            process,
            command,
            workdir=workdir,
            env=env,
            wall_timeout_s=wall_timeout_s,
            cancel=cancel,
            on_progress=on_progress,
        )

    monkeypatch.setattr(EpisodeProcess, "run", watch)

    def episode(backend: GazeboNav2Backend, request: EpisodeRequest) -> EpisodeResult:
        backend.prepare()
        return backend.run_episode(request, backend.materialize(request))

    requests = tuple(
        EpisodeRequest(
            run_id=uuid4(),
            scenario=space.make_scenario({"obstacle.clearance": clearance}),
            task=space.task,
            sut_profile=profile,
            seed=192,
            workdir=tmp_path / label,
            sim_time_budget_s=120.0,
            wall_timeout_s=450.0,
        )
        for label, clearance in (("near", 0.25), ("far", 0.95))
    )
    backends = [GazeboNav2Backend(settings), GazeboNav2Backend(settings)]
    with ThreadPoolExecutor(2) as pool, ExitStack() as markers:
        futures = [
            pool.submit(episode, backend, req)
            for backend, req in zip(backends, requests, strict=True)
        ]
        try:
            by_workdir = dict(launch_environments.get(timeout=45.0) for _ in requests)
            first, second = (by_workdir[req.workdir.resolve()] for req in requests)
            assert first["ROS_DOMAIN_ID"] != second["ROS_DOMAIN_ID"]
            assert first["GZ_PARTITION"] != second["GZ_PARTITION"]
            for env, marker in zip((first, second), _PROBES, strict=True):
                context = rclpy.Context()
                rclpy.init(args=[], context=context, domain_id=int(env["ROS_DOMAIN_ID"]))
                markers.callback(context.shutdown)
                probe = rclpy.create_node(marker[1:], context=context)
                markers.callback(probe.destroy_node)
            _assert_separate_graphs(ros2, (first, second))
            near, far = (future.result(timeout=450.0) for future in futures)
        finally:
            for backend in backends:
                backend.cancel()
    assert near.infra_error is None
    assert far.infra_error is None
    samples = min(near.trace.n_samples, far.trace.n_samples)
    assert samples > 1
    assert not np.allclose(
        near.trace.min_obstacle_dist[:samples], far.trace.min_obstacle_dist[:samples], atol=0.02
    )
