"""Backend registry (T-035a; docs/05 §2.1)."""

from __future__ import annotations

from types import SimpleNamespace

import pytest

from roboprobe.backends.base import (
    PLUGIN_API_VERSION,
    BackendCapabilities,
    assert_supports,
)
from roboprobe.backends.registry import ENTRY_POINT_GROUP, get_backend
from roboprobe.core import errors
from roboprobe.core.settings import RoboProbeSettings

pytestmark = pytest.mark.unit


class _Dummy:
    PLUGIN_API_VERSION = PLUGIN_API_VERSION

    def __init__(self, settings: RoboProbeSettings) -> None:
        self.settings = settings
        self.capabilities = BackendCapabilities(
            name="dummy",
            supported_params=frozenset({"robot.max_speed"}),
            deterministic=True,
            typical_episode_wall_s=1.0,
            max_parallel_per_host=1,
        )


class _Stale:
    PLUGIN_API_VERSION = PLUGIN_API_VERSION + 1

    def __init__(self, settings: RoboProbeSettings) -> None:
        del settings


def test_registry_loads_monkeypatched_entry_point(monkeypatch: pytest.MonkeyPatch) -> None:
    ep = SimpleNamespace(name="dummy", load=lambda: _Dummy)
    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group=None: [ep] if group == ENTRY_POINT_GROUP else [],
    )
    backend = get_backend("dummy", RoboProbeSettings())
    assert isinstance(backend, _Dummy)


def test_unknown_name_is_plugin_error(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("importlib.metadata.entry_points", lambda group=None: [])
    with pytest.raises(errors.PluginError, match="unknown backend"):
        get_backend("nope", RoboProbeSettings())


def test_version_mismatch_is_plugin_error(monkeypatch: pytest.MonkeyPatch) -> None:
    ep = SimpleNamespace(name="stale", load=lambda: _Stale)
    monkeypatch.setattr(
        "importlib.metadata.entry_points",
        lambda group=None: [ep] if group == ENTRY_POINT_GROUP else [],
    )
    with pytest.raises(errors.PluginError, match="PLUGIN_API_VERSION"):
        get_backend("stale", RoboProbeSettings())


def test_assert_supports_rejects_unknown_param() -> None:
    caps = BackendCapabilities(
        name="dummy",
        supported_params=frozenset({"robot.max_speed"}),
        deterministic=True,
        typical_episode_wall_s=1.0,
        max_parallel_per_host=1,
    )
    with pytest.raises(errors.ValidationError) as exc:
        assert_supports(caps, ["robot.max_speed", "env.magic"])
    assert exc.value.code is errors.ErrorCode.BACKEND_UNSUPPORTED_PARAM
    assert_supports(caps, ["robot.max_speed"])
