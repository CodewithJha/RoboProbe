"""Campaign HTML report unit tests (T-078b)."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from html.parser import HTMLParser
from pathlib import Path
from types import SimpleNamespace
from typing import Any
from uuid import UUID, uuid4

import pytest

from roboprobe.reporting.campaign import render_campaign_report

pytestmark = pytest.mark.unit

CID = UUID("00000000-0000-4000-8000-000000000101")


@dataclass
class _Run:
    id: UUID
    ordinal: int
    repeat_index: int = 0
    verdict: str = "PASS"
    x_unit: tuple[float, ...] = (0.1, 0.2)
    phase: str = ""
    tags: tuple[str, ...] = ()
    metrics: dict[str, float] = field(default_factory=lambda: {"duration_s": 1.0})
    manifest_sha256: str = "abc"


@dataclass
class _Page:
    items: list[_Run]


@dataclass
class _Campaign:
    name: str = "demo"
    backend: str = "kinematic2d"
    strategy_id: str = "S-RANDOM"
    budget: int = 10
    seed: int = 1


@dataclass
class _Mode:
    code: str
    label: str
    size: int
    primary_class: str = "F-COL"
    class_mix: dict[str, Any] = field(default_factory=dict)
    rules: list[dict[str, str]] = field(default_factory=list)
    interaction: dict[str, str] | None = None
    medoid_run_id: UUID | None = None
    minimal_run_id: UUID | None = None


class _RunsRepo:
    def __init__(self, runs: list[_Run]) -> None:
        self._runs = runs

    def list_for_campaign(self, _cid: UUID, limit: Any = None) -> _Page:
        del limit
        return _Page(items=self._runs)


class _FakeUow:
    def __init__(self) -> None:
        rid = uuid4()
        self.campaigns = type("C", (), {"get": lambda _s, _id: _Campaign()})()
        self.runs = _RunsRepo(
            [
                _Run(rid, 1, verdict="FAIL"),
                _Run(uuid4(), 2, verdict="PASS"),
            ]
        )
        self.modes = type(
            "M",
            (),
            {"list_for_campaign": lambda _s, _id: [_Mode("M-01", "collision", 2)]},
        )()
        self.analyses = type("A", (), {"list_for_campaign": lambda _s, _id: ()})()
        self.risk_maps = type("R", (), {"latest": lambda _s, _id: None})()
        self.artifacts = type("Ar", (), {"get": lambda _s, _id: None})()


class _FakeStore:
    def put(self, src: Path, kind: str, **kwargs: Any) -> Any:
        del kind, kwargs
        return type("Ref", (), {"sha256": "00" * 32, "rel_path": src.name})()

    def path(self, ref: Any) -> Path:
        return Path(ref.rel_path)


class _LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.external: list[str] = []

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        for key, value in attrs:
            if key in {"href", "src"} and value and re.match(r"https?://", value):
                self.external.append(value)


def test_render_campaign_report_offline_html(tmp_path: Path) -> None:
    out = tmp_path / "report.html"
    path = render_campaign_report(CID, _FakeUow(), _FakeStore(), out=out)
    html = path.read_text(encoding="utf-8")
    assert "<svg" in html
    assert "Campaign report" in html
    parser = _LinkParser()
    parser.feed(html)
    assert parser.external == []


def test_report_renders_legacy_json_risk_regions(tmp_path: Path) -> None:
    """Older records still supply a plotted risk slice."""
    risk = tmp_path / "risk.json"
    risk.write_text(
        json.dumps(
            [
                {
                    "x_param": "robot.max_speed",
                    "y_param": "env.illuminance",
                    "x_values": [0.1, 0.2],
                    "y_values": [1.0, 2.0, 3.0],
                    "region": [[0, 1, 2], [0, 0, 1]],
                }
            ]
        ),
        encoding="utf-8",
    )
    uow = _FakeUow()
    uow.risk_maps = SimpleNamespace(latest=lambda _id: SimpleNamespace(slices_artifact="risk"))
    uow.artifacts = SimpleNamespace(get=lambda _id: SimpleNamespace(sha256="0" * 64, rel_path=risk))
    out = render_campaign_report(CID, uow, _FakeStore(), out=tmp_path / "report.html")
    assert "robot.max_speed x env.illuminance" in out.read_text(encoding="utf-8")


def test_xss_escaped_mode_label(tmp_path: Path) -> None:
    uow = _FakeUow()
    uow.modes = type(
        "M",
        (),
        {"list_for_campaign": lambda _s, _id: [_Mode("M-01", "<script>alert(1)</script>", 1)]},
    )()
    render_campaign_report(CID, uow, _FakeStore(), out=tmp_path / "x.html")
    text = (tmp_path / "x.html").read_text(encoding="utf-8")
    assert "<script>alert" not in text
