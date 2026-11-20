"""Cheap unit coverage for campaign CLI helpers (no CliRunner I/O)."""

from __future__ import annotations

from types import SimpleNamespace
from uuid import uuid4

import pytest

from roboprobe.cli import campaign as campaign_mod
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.types import CampaignStatus, RunStatus, Verdict

pytestmark = pytest.mark.unit


def test_resolve_seed_and_mappings() -> None:
    assert campaign_mod._resolve_seed({"seed": 7}, None) == 7
    assert campaign_mod._resolve_seed({"seed": 1}, 99) == 99
    assert campaign_mod._as_mapping(None) == {}
    assert campaign_mod._as_mapping({"a": 1}) == {"a": 1}
    assert campaign_mod._as_mapping("x") == {}
    assert campaign_mod._as_str_tuple(None) == ()
    assert campaign_mod._as_str_tuple(["a", "b"]) == ("a", "b")
    assert campaign_mod._as_str_tuple("x") == ()
    assert campaign_mod._status_value(RunStatus.DONE) == "DONE"
    assert campaign_mod._status_value(Verdict.FAIL) == "FAIL"
    assert campaign_mod._status_value(CampaignStatus.RUNNING) == "RUNNING"
    assert campaign_mod._status_value("X") == "X"


def test_parse_id_and_list_runs() -> None:
    cid = uuid4()
    assert campaign_mod._parse_id(str(cid)) == cid
    with pytest.raises(ValidationError):
        campaign_mod._parse_id("not-a-uuid")

    class _Page:
        def __init__(self, items: list[object], next_cursor: str | None = None) -> None:
            self.items = items
            self.next_cursor = next_cursor

    class _Uow:
        class runs:
            @staticmethod
            def list_for_campaign(
                _cid: object, *, limit: int | None = None, cursor: str | None = None
            ) -> _Page:
                del limit
                if cursor is None:
                    return _Page([1], next_cursor="c1")
                return _Page([2], next_cursor=None)

    assert campaign_mod._list_runs(_Uow(), cid) == [1, 2]


def test_ensure_sut_missing(monkeypatch: pytest.MonkeyPatch, tmp_path) -> None:
    monkeypatch.setattr(campaign_mod, "_SUT_DIR", tmp_path)
    with pytest.raises(NotFoundError):
        campaign_mod._ensure_sut(SimpleNamespace(), "missing", "kinematic2d")
