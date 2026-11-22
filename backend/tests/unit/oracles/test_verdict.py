"""VerdictEngine (T-039a; docs/08 §5)."""

from __future__ import annotations

import pytest
from tests.factories import make_trace
from tests.fixtures.traces.make_golden_traces import TRACES
from tests.unit.oracles.conftest import FakeEpisode, make_task

from roboprobe.core.settings import OracleThresholds
from roboprobe.core.types import FailureClass, OracleResult, TaskSpec, Trace, Verdict
from roboprobe.oracles import VerdictEngine, create_all
from roboprobe.oracles.base import Oracle
from roboprobe.oracles.verdict import PRIMARY_TIE_BREAK

pytestmark = pytest.mark.unit


def test_invalid_on_infra_error() -> None:
    engine = VerdictEngine(create_all(OracleThresholds()))
    out = engine.judge(FakeEpisode(TRACES["straight_pass"](), infra_error="boom"), make_task())
    assert out.verdict is Verdict.INVALID
    assert out.robustness is None
    assert out.primary_failure is FailureClass.INFRA


def test_fail_iff_rho_negative_on_goldens() -> None:
    engine = VerdictEngine(create_all(OracleThresholds()))
    task = make_task()
    for trace in TRACES.values():
        out = engine.judge(FakeEpisode(trace()), task)
        if out.verdict is Verdict.INVALID:
            continue
        fail = out.verdict is Verdict.FAIL
        assert fail == (out.robustness is not None and out.robustness < 0.0)


def test_tie_break_order() -> None:
    class _Stub(Oracle):
        id = "O-STUB"
        failure_class = FailureClass.COL
        severity = "failure"

        def __init__(self, oracle_id: str, cls: FailureClass, t: float) -> None:
            super().__init__(OracleThresholds())
            self._id = oracle_id
            self._cls = cls
            self._t = t

        def evaluate(self, trace: Trace, task: TaskSpec) -> OracleResult:
            return OracleResult(
                oracle_id=self._id,
                failure_class=self._cls,
                severity="failure",
                robustness=-0.2,
                violated=True,
                first_violation_t=self._t,
                details={},
            )

    t = 3.0
    stubs = [_Stub(f"O-{cls.name}", cls, t) for cls in reversed(PRIMARY_TIE_BREAK)]
    engine = VerdictEngine(stubs)
    out = engine.judge(FakeEpisode(TRACES["straight_pass"]()), make_task())
    assert out.primary_failure is FailureClass.COL
    later = [_Stub("O-COL", FailureClass.COL, 5.0), _Stub("O-INST", FailureClass.INST, 1.0)]
    out2 = VerdictEngine(later).judge(FakeEpisode(TRACES["straight_pass"]()), make_task())
    assert out2.primary_failure is FailureClass.INST


def test_warnings_do_not_fail() -> None:
    engine = VerdictEngine(create_all(OracleThresholds()))
    out = engine.judge(FakeEpisode(TRACES["oscillation"]()), make_task())
    assert out.verdict is Verdict.PASS
    osc = next(r for r in out.oracle_results if r.oracle_id == "O-OSC")
    assert osc.violated
    assert osc.severity == "warning"


@pytest.mark.parametrize(
    ("raw", "infra_error", "expected", "robustness"),
    [
        ("0.42", None, Verdict.PASS, 0.42),
        ("-0.19", None, Verdict.FAIL, -0.19),
        ("0", None, Verdict.PASS, 0.0),
        ("0.42", "backend offline", Verdict.INVALID, None),
        ("nan", None, Verdict.INVALID, None),
        ("1.2", None, Verdict.INVALID, None),
        ("no value", None, Verdict.INVALID, None),
        (None, None, Verdict.INVALID, None),
    ],
)
def test_analytic_backend_verdict_uses_declared_rho(
    raw: str | None,
    infra_error: str | None,
    expected: Verdict,
    robustness: float | None,
) -> None:
    class AnalyticEpisode:
        trace = make_trace(n=2)
        backend_meta: dict[str, str] = {"rho": raw} if raw is not None else {}

        def __init__(self) -> None:
            self.infra_error = infra_error

    result = AnalyticEpisode()
    engine = VerdictEngine(create_all(OracleThresholds()), direct_rho=True)
    out = engine.judge(result, make_task())
    assert out.verdict is expected
    assert out.robustness == robustness
    assert (
        VerdictEngine(create_all(OracleThresholds())).judge(result, make_task()).verdict
        is Verdict.INVALID
    )
