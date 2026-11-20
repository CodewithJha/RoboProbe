"""Unit coverage for offline reevaluate helpers (T-039b). Fast, fully stubbed."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from roboprobe.core.errors import NotFoundError
from roboprobe.core.types import RunOutcome, Verdict
from roboprobe.oracles import reevaluate as reevaluate_mod
from roboprobe.oracles.reevaluate import _persist_outcome, _verdict_str, reevaluate_run

pytestmark = pytest.mark.unit


def test_verdict_str() -> None:
    assert _verdict_str(None) is None
    assert _verdict_str(Verdict.PASS) == "PASS"
    assert _verdict_str("FAIL") == "FAIL"


def test_persist_outcome_noop_and_with_session(monkeypatch: pytest.MonkeyPatch) -> None:
    outcome = RunOutcome(
        verdict=Verdict.PASS,
        robustness=1.0,
        primary_failure=None,
        metrics={},
        oracle_results=(),
    )
    _persist_outcome(object(), uuid4(), outcome, campaign_id=uuid4())

    run_row = SimpleNamespace(verdict=None, robustness=None, primary_failure=None, metrics={})
    campaign_row = SimpleNamespace(oracle_config={})
    session = SimpleNamespace(
        get=lambda model, key: run_row if "Run" in getattr(model, "__name__", "") else campaign_row
    )
    monkeypatch.setattr(
        reevaluate_mod,
        "importlib",
        SimpleNamespace(
            import_module=lambda name: SimpleNamespace(RunRow=type("RunRow", (), {}), CampaignRow=type("CampaignRow", (), {}))
            if name == "roboprobe.store.orm"
            else (_ for _ in ()).throw(AssertionError(name))
        ),
    )
    _persist_outcome(SimpleNamespace(_session=session), uuid4(), outcome, campaign_id=uuid4())
    assert run_row.verdict == "PASS"
    assert campaign_row.oracle_config.get("oracle_set_version")


def _patch_judge(monkeypatch: pytest.MonkeyPatch, outcome: RunOutcome) -> None:
    monkeypatch.setattr(reevaluate_mod, "create_all", lambda _cfg: ())
    monkeypatch.setattr(
        reevaluate_mod,
        "VerdictEngine",
        lambda _o: SimpleNamespace(judge=lambda *_a, **_k: outcome),
    )
    # Patch only the name used inside reevaluate_run, not stdlib importlib globally.
    real_import = reevaluate_mod.importlib.import_module

    def _import(name: str) -> object:
        if name == "roboprobe.backends.trace_io":
            return SimpleNamespace(read_trace=lambda _p: object())
        if name == "roboprobe.store.records":
            return SimpleNamespace(OracleResultRecord=lambda **kw: SimpleNamespace(**kw))
        return real_import(name)

    monkeypatch.setattr(reevaluate_mod.importlib, "import_module", _import)


def test_reevaluate_not_found(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    path = tmp_path / "t.parquet"
    path.write_bytes(b"x")
    _patch_judge(
        monkeypatch,
        RunOutcome(
            verdict=Verdict.PASS,
            robustness=1.0,
            primary_failure=None,
            metrics={},
            oracle_results=(),
        ),
    )

    class _Uow:
        runs = SimpleNamespace(get=lambda _r: None)

        def __enter__(self) -> _Uow:
            return self

        def __exit__(self, *a: object) -> None:
            del a

    with pytest.raises(NotFoundError):
        reevaluate_run(
            lambda: _Uow(),
            uuid4(),
            task=SimpleNamespace(),  # type: ignore[arg-type]
            artifact_path=path,
            write=False,
        )


def test_reevaluate_write(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    path = tmp_path / "t.parquet"
    path.write_bytes(b"x")
    rid = uuid4()
    replaced: list[object] = []
    _patch_judge(
        monkeypatch,
        RunOutcome(
            verdict=Verdict.PASS,
            robustness=1.0,
            primary_failure=None,
            metrics={},
            oracle_results=(),
        ),
    )

    class _Uow:
        def __init__(self) -> None:
            self.runs = SimpleNamespace(
                get=lambda _r: SimpleNamespace(
                    verdict=Verdict.FAIL, robustness=0.1, campaign_id=uuid4()
                )
            )
            self.oracle_results = SimpleNamespace(
                replace_for_run=lambda run_id, rows: replaced.append((run_id, rows))
            )
            self._session = None

        def __enter__(self) -> _Uow:
            return self

        def __exit__(self, *a: object) -> None:
            del a

        def commit(self) -> None:
            return None

    diff = reevaluate_run(
        lambda: _Uow(),
        rid,
        task=SimpleNamespace(),  # type: ignore[arg-type]
        artifact_path=path,
        write=True,
    )
    assert diff.changed is True
    assert replaced
