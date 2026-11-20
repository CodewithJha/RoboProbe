"""ReplayBackend (T-035c)."""

from __future__ import annotations

from pathlib import Path
from uuid import uuid4

import pytest
from tests.factories import make_scenario, make_trace

from roboprobe.backends.base import EpisodeRequest, episode_timeouts
from roboprobe.backends.replay.backend import ReplayBackend
from roboprobe.backends.trace_io import write_trace
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import SutProfile
from roboprobe.scenario.task import load_task

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[4]


def test_returned_trace_equals_stored(tmp_path: Path) -> None:
    trace = make_trace()
    source = tmp_path / "src.parquet"
    write_trace(trace, source)
    run_id = uuid4()
    settings = RoboProbeSettings()
    backend = ReplayBackend(settings, traces={run_id: source})
    sim, wall = episode_timeouts(settings.worker)
    req = EpisodeRequest(
        run_id=run_id,
        scenario=make_scenario(),
        task=load_task(REPO / "tasks" / "warehouse_delivery_v1.yaml", strict=False),
        sut_profile=SutProfile(id="replay", backend="replay", config={}, config_hash="b" * 16),
        seed=0,
        workdir=tmp_path / "work",
        sim_time_budget_s=sim,
        wall_timeout_s=wall,
    )
    req.workdir.mkdir()
    materialized = backend.materialize(req)
    result = backend.run_episode(req, materialized)
    assert result.infra_error is None
    assert result.trace.n_samples == trace.n_samples
    assert list(result.trace.t) == list(trace.t)
