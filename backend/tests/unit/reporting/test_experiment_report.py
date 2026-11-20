"""Experiment HTML report unit tests (T-079)."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any
from uuid import UUID, uuid4

import pytest

from roboprobe.core.types import CampaignStatus
from roboprobe.reporting.experiment import build_experiment_context, render_experiment_report

pytestmark = pytest.mark.unit

EID = UUID("00000000-0000-4000-8000-000000000202")


@dataclass
class _Campaign:
    id: UUID
    strategy_id: str = "S-RANDOM"
    budget: int = 5
    status: CampaignStatus = CampaignStatus.COMPLETED
    experiment_rep: int = 0
    tags: tuple[str, ...] = ("variant:RANDOM",)


@dataclass
class _Run:
    ordinal: int
    verdict: str
    x_unit: tuple[float, ...] = (0.0, 0.0)
    phase: str = ""
    tags: tuple[str, ...] = ()
    metrics: dict[str, float] = field(default_factory=lambda: {"duration_s": 1.0})
    repeat_index: int = 0


@dataclass
class _Page:
    items: list[_Run]


class _FakeUow:
    def __init__(self) -> None:
        self._cid = uuid4()
        self.campaigns = type(
            "C",
            (),
            {"list_for_experiment": lambda _s, _id: [_Campaign(self._cid, tags=("variant:A",))]},
        )()
        self.experiments = type(
            "E",
            (),
            {
                "get": lambda _s, _id: type(
                    "Exp",
                    (),
                    {
                        "name": "exp",
                        "design": {
                            "budget": 5,
                            "backend": "kinematic2d",
                            "metrics": ["MET-01", "MET-03"],
                            "seeds": {"root": 42},
                        },
                        "results": {},
                    },
                )()
            },
        )()
        self.runs = type(
            "R",
            (),
            {
                "list_for_campaign": lambda _s, _cid, limit=None: _Page(
                    items=[
                        _Run(1, "FAIL"),
                        _Run(2, "PASS"),
                        _Run(3, "FAIL"),
                    ]
                )
            },
        )()


class _FakeStore:
    def put(self, src: Path, kind: str, **kwargs: Any) -> Any:
        del kind, kwargs
        return None


def test_experiment_report_lists_all_strategies(tmp_path: Path) -> None:
    ctx = build_experiment_context(EID, _FakeUow())
    assert ctx.strategies
    for metric in ctx.metrics:
        assert metric in ctx.boxplots
    path = render_experiment_report(EID, _FakeUow(), _FakeStore(), out=tmp_path / "e.html")
    html = path.read_text(encoding="utf-8")
    for label in ctx.strategies:
        assert label in html
    for row in ctx.stats_rows:
        if row["p"] and row["p_holm"]:
            assert float(row["p_holm"]) >= float(row["p"]) or row["p"] == "nan"
