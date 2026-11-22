"""Gazebo bag selection and the stored MCAP download path (T-097b)."""

from __future__ import annotations

import hashlib
import re
import shutil
import subprocess
from pathlib import Path
from types import SimpleNamespace
from uuid import UUID, uuid4

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import Engine

from roboprobe.api.app import create_app
from roboprobe.backends.gazebo_nav2.bags import should_record_bag
from roboprobe.bootstrap._infra import Infrastructure, build_infrastructure
from roboprobe.bootstrap.worker import build_worker
from roboprobe.core.settings import load_settings
from roboprobe.core.settings.backends import GazeboNav2Settings, RecordBagPolicy
from roboprobe.core.types import CampaignStatus, FailureClass, RunOutcome, RunStatus, Verdict
from roboprobe.runner.replay import ReplayRequest, enqueue_replays
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.sut_profile import config_hash, load_sut_profile
from roboprobe.store.orm import Base
from roboprobe.store.records import CampaignRecord, NewRun, SpaceRecord, SutProfileRecord

REPO = Path(__file__).resolve().parents[3]
MCAP_MAGIC = b"\x89MCAP0\r\n"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("phase", "source_verdict", "failures"),
    [
        ("baseline", None, False),
        ("explore", None, False),
        ("confirm", None, True),
        ("manual", None, True),
        ("replay", None, False),
        ("replay", Verdict.PASS, False),
        ("replay", Verdict.FAIL, True),
        ("replay", Verdict.INVALID, False),
    ],
)
@pytest.mark.parametrize("policy", ["never", "failures", "always"])
def test_recording_policy_truth_table(
    phase: str, source_verdict: Verdict | None, failures: bool, policy: RecordBagPolicy
) -> None:
    run = SimpleNamespace(phase=phase, source_verdict=source_verdict)
    expected = {"never": False, "failures": failures, "always": True}
    assert should_record_bag(run, GazeboNav2Settings(record_bag=policy)) is expected[policy]


def _seed_source_run(infra: Infrastructure, space: ScenarioSpace) -> UUID:
    nominal = space.nominal()
    sut = load_sut_profile(REPO / "configs/sut_profiles/tb4_nav2_default.yaml", strict=True)
    # Allow BT action acknowledgements on busy software-rendered runners.
    config = {
        **sut.config,
        "nav2_overrides": {"bt_navigator": {"ros__parameters": {"default_server_timeout": 1000}}},
    }
    cid = uuid4()
    with infra.uow_factory() as uow:
        uow.sut_profiles.add(
            SutProfileRecord(
                id=sut.id,
                backend=sut.backend,
                config=config,
                config_hash=config_hash(sut.backend, config),
            )
        )
        uow.spaces.add(
            SpaceRecord(id=space.id, version=space.version, name="warehouse", definition={})
        )
        uow.campaigns.add(
            CampaignRecord(
                id=cid,
                name="Gazebo bag recording",
                space_id=space.id,
                space_version=space.version,
                sut_profile_id=sut.id,
                backend="gazebo_nav2",
                strategy_id="S-RANDOM",
                seed=1,
                budget=2,
                oracle_config={},
                status=CampaignStatus.RUNNING,
            )
        )
        (source_id,) = uow.runs.insert_batch(
            [
                NewRun(
                    campaign_id=cid,
                    ordinal=0,
                    backend="gazebo_nav2",
                    scenario_hash=nominal.scenario_hash,
                    scenario_values=nominal.values,
                    x_unit=tuple(float(x) for x in space.to_unit(nominal.values)),
                    seed=1,
                    phase="baseline",
                )
            ]
        )
        uow.commit()
    return source_id


@pytest.mark.sim
@pytest.mark.timeout(600)
def test_replay_of_failed_gazebo_run_downloads_bag(
    request: pytest.FixtureRequest, pg_engine: Engine, tmp_path: Path
) -> None:
    ros = shutil.which("ros2")
    if request.config.getoption("--backend") != "gazebo_nav2" or ros is None:
        pytest.skip("requires the sourced Jazzy worker image and --backend gazebo_nav2")

    settings = load_settings(
        {
            "database.url": pg_engine.url.render_as_string(hide_password=False),
            "storage.workdir_root": tmp_path / "workdir",
            "storage.artifact_root": tmp_path / "artifacts",
            "worker.backend": "gazebo_nav2",
            "worker.default_sim_time_budget_s": 10.0,
            "worker.default_wall_timeout_s": 420.0,
            "backends.gazebo_nav2.record_bag": "failures",
            "observability.metrics_enabled": False,
        }
    )
    space = ScenarioSpace.from_yaml(
        REPO / "configs/scenario_spaces/warehouse_v1.yaml", base_dir=REPO, strict_task=True
    )
    Base.metadata.create_all(pg_engine)
    infra = build_infrastructure(settings)
    worker = build_worker(settings, task=space.task, infra=infra)
    try:
        worker.backend.prepare()
        source_id = _seed_source_run(infra, space)
        claimed = worker.claim()
        assert claimed is not None and claimed.run_id == source_id
        # Seed a completed failure through the real queue, then execute the replay in Gazebo.
        infra.queue.mark_running(source_id)
        infra.queue.mark_evaluating(source_id)
        infra.queue.complete(
            source_id,
            RunOutcome(
                verdict=Verdict.FAIL,
                robustness=-1.0,
                primary_failure=FailureClass.TIMEOUT,
                oracle_results=(),
                metrics={},
            ),
        )

        (replay_id,) = enqueue_replays(infra.uow_factory, ReplayRequest(run_id=source_id))
        replay = worker.claim()
        assert replay is not None and replay.run_id == replay_id
        assert replay.phase == "replay" and replay.source_verdict is Verdict.FAIL
        worker.execute(replay)
        with infra.uow_factory() as uow:
            result = uow.runs.get(replay_id)
            assert result is not None and result.status is RunStatus.DONE, result

        app = create_app(settings)
        app.state.services = infra
        app.state.event_hub_autostart = False
        with TestClient(app) as client:
            listing = client.get(f"/api/v1/runs/{replay_id}/artifacts")
            assert listing.status_code == 200, listing.text
            [bag] = [item for item in listing.json() if item["kind"] == "bag"]
            response = client.get(f"/api/v1/artifacts/{bag['id']}/content")
            assert response.status_code == 200, response.text
            assert response.content.startswith(MCAP_MAGIC) and response.content.endswith(MCAP_MAGIC)
            assert len(response.content) == bag["size_bytes"]
            assert hashlib.sha256(response.content).hexdigest() == bag["sha256"]
            assert response.headers["etag"] == f'"{bag["sha256"]}"'
            assert ".mcap" in response.headers["content-disposition"]

            downloaded = tmp_path / "downloaded.mcap"
            downloaded.write_bytes(response.content)
            info = subprocess.run(  # noqa: S603 - executable and path come from the local fixture
                [ros, "bag", "info", "-s", "mcap", str(downloaded)],
                capture_output=True,
                check=True,
                text=True,
            )
            assert re.search(r"^Messages:\s+[1-9][0-9]*", info.stdout, re.MULTILINE), info.stdout
            assert "/scan" in info.stdout
            assert "/tf" in info.stdout
    finally:
        worker.backend.shutdown()
        infra.close()
