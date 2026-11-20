"""Strategy registry discovery (T-050a)."""

from __future__ import annotations

import pytest
from tests.unit.selection.conftest import load_space

from roboprobe.core import errors
from roboprobe.selection.base import Strategy
from roboprobe.selection.registry import available, create, get, register

pytestmark = pytest.mark.unit

BUILTINS = ("S-RANDOM", "S-LHS", "S-SOBOL", "S-GRID", "S-OFAT")


def test_available_lists_builtins() -> None:
    ids = available()
    for strategy_id in BUILTINS:
        assert strategy_id in ids


def test_get_and_create_round_trip() -> None:
    _, ctx = load_space()
    cls = get("S-RANDOM")
    assert issubclass(cls, Strategy)
    inst = create("S-RANDOM", ctx)
    assert inst.id == "S-RANDOM"


def test_unknown_id_lists_available() -> None:
    with pytest.raises(errors.PluginError, match="S-NOPE") as exc:
        get("S-NOPE")
    assert "S-RANDOM" in str(exc.value)


def test_duplicate_id_is_rejected() -> None:
    class Other(Strategy):
        id = "S-RANDOM"

        def _propose_impl(self, history, pending, q, rng):
            del history, pending, q, rng
            return []

    with pytest.raises(errors.PluginError, match="duplicate"):
        register(Other)


def test_wrong_api_version_is_rejected() -> None:
    class Old(Strategy):
        id = "S-OLD"
        PLUGIN_API_VERSION = 0

        def _propose_impl(self, history, pending, q, rng):
            del history, pending, q, rng
            return []

    with pytest.raises(errors.PluginError, match="plugin API"):
        register(Old)
