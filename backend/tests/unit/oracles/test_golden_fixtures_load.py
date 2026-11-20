"""Golden traces load, validate, and match hand formulas (T-019)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml
from tests.fixtures.traces.make_golden_traces import TRACES, write_all
from tests.unit.oracles.conftest import FakeEpisode, make_task

from roboprobe.backends import trace_io
from roboprobe.core.settings import OracleThresholds
from roboprobe.core.types import FailureClass, Verdict
from roboprobe.oracles import VerdictEngine, create_all

pytestmark = pytest.mark.unit

FIXTURE_DIR = Path(__file__).resolve().parents[2] / "fixtures" / "traces"
EXPECTED = yaml.safe_load((FIXTURE_DIR / "expected.yaml").read_text(encoding="utf-8"))
TOL = 1e-9


@pytest.fixture(scope="module", autouse=True)
def _parquet() -> None:
    write_all(FIXTURE_DIR)


@pytest.mark.parametrize("name", list(TRACES))
def test_fixture_loads_and_validates(name: str) -> None:
    path = FIXTURE_DIR / f"{name}.parquet"
    trace = trace_io.read_trace(path)
    assert trace.n_samples >= 2
    problems = trace_io.validate_trace(trace, min_hz=10.0, max_gap_s=0.2)
    assert problems == ()
    rebuilt = TRACES[name]()
    assert rebuilt.n_samples == trace.n_samples


@pytest.mark.parametrize("name", list(TRACES))
def test_oracles_match_hand_formulas(name: str) -> None:
    spec = EXPECTED[name]
    engine = VerdictEngine(create_all(OracleThresholds()))
    outcome = engine.judge(FakeEpisode(TRACES[name]()), make_task())
    by_id = {r.oracle_id: r for r in outcome.oracle_results}
    for oracle_id, want in spec["r"].items():
        assert by_id[oracle_id].robustness == pytest.approx(want, abs=TOL), oracle_id
    assert outcome.verdict is Verdict(spec["verdict"])
    primary = spec["primary"]
    if primary is None:
        assert outcome.primary_failure is None
    else:
        assert outcome.primary_failure is FailureClass(primary)
    assert outcome.robustness == pytest.approx(spec["rho"], abs=TOL)
