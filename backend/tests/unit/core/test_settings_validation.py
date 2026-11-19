from pathlib import Path
from typing import Any

import pytest
from pydantic import ValidationError

from roboprobe.core.errors import ConfigError, ErrorCode
from roboprobe.core.settings import RoboProbeSettings, load_settings
from roboprobe.core.settings.api import ApiSettings, is_loopback_host

pytestmark = pytest.mark.unit


def _error_locs(overrides: dict[str, Any]) -> set[str]:
    with pytest.raises(ConfigError) as info:
        load_settings(overrides)
    assert info.value.code is ErrorCode.CONFIG_INVALID
    return {err["loc"] for err in info.value.context["errors"]}  # type: ignore[index, union-attr]


def test_all_errors_are_reported_together(settings_env: Path) -> None:
    locs = _error_locs(
        {
            "env": "staging",
            "worker.concurrency": 0,
            "oracles.loc.e_max": -1,
            "backends.gazebo_nav2.record_bag": "sometimes",
            "bogus_section": {},
        }
    )
    assert locs == {
        "env",
        "worker.concurrency",
        "oracles.loc.e_max",
        "backends.gazebo_nav2.record_bag",
        "bogus_section",
    }


def test_errors_never_echo_input_values(settings_env: Path) -> None:
    with pytest.raises(ConfigError) as info:
        load_settings({"api.host": "0.0.0.0", "api.port": "not-a-port-s3cr3t"})
    assert "s3cr3t" not in repr(info.value.context)
    assert "s3cr3t" not in str(info.value)


@pytest.mark.parametrize(
    "overrides",
    [
        {"runner": {"tick": 1}},  # typo inside a section
        {"oracles.loc.e_maxx": 0.4},
    ],
)
def test_unknown_nested_keys_are_rejected(settings_env: Path, overrides: dict[str, Any]) -> None:
    with pytest.raises(ConfigError):
        load_settings(overrides)


def test_unknown_toml_section_is_rejected(settings_env: Path) -> None:
    (settings_env / "roboprobe.toml").write_text("[runnr]\ntick_interval_s = 1\n")
    assert _error_locs({}) == {"runnr"}


def test_invalid_toml_syntax(settings_env: Path) -> None:
    (settings_env / "roboprobe.toml").write_text("[runner\n")
    with pytest.raises(ConfigError, match="cannot parse TOML"):
        load_settings()


def test_non_loopback_host_requires_token(settings_env: Path) -> None:
    assert _error_locs({"api.host": "0.0.0.0"}) == {"api"}
    settings = load_settings({"api": {"host": "0.0.0.0", "token": "t"}})
    assert settings.api.host == "0.0.0.0"


@pytest.mark.parametrize(
    ("host", "loopback"),
    [
        ("127.0.0.1", True),
        ("127.0.0.2", True),
        ("::1", True),
        ("[::1]", True),
        ("localhost", True),
        ("LocalHost", True),
        ("0.0.0.0", False),
        ("::", False),
        ("10.0.0.5", False),
        ("api.example.test", False),
    ],
)
def test_is_loopback_host(host: str, loopback: bool) -> None:
    assert is_loopback_host(host) is loopback


@pytest.mark.parametrize(
    ("overrides", "loc"),
    [
        ({"api": {"page_limit_default": 600}}, "api"),
        ({"runner": {"retry": {"base_delay_s": 20}}}, "runner.retry"),
        ({"selection": {"probe": {"weights": {"refine": 0.5}}}}, "selection.probe.weights"),
        ({"selection": {"ofat": {"levels": [0.0]}}}, "selection.ofat.levels"),
        ({"selection": {"ofat": {"levels": [0.0, 0.5, 0.5]}}}, "selection.ofat.levels"),
        ({"selection": {"ofat": {"levels": [0.0, 1.5]}}}, "selection.ofat.levels"),
        ({"risk": {"thresholds": {"safe": 0.9, "failure": 0.5}}}, "risk.thresholds"),
        ({"worker": {"heartbeat_interval_s": 30}}, ""),
        ({"database": {"url": "mysql://u@h/db"}}, "database"),
        ({"database": {"notify_channel": "Bad-Channel"}}, "database.notify_channel"),
        ({"api": {"base_path": "api/v1/"}}, "api.base_path"),
        (
            {"backends": {"gazebo_nav2": {"domain_id_base": 500}}},
            "backends.gazebo_nav2.domain_id_base",
        ),
        ({"observability": {"otlp_endpoint": "not a url"}}, "observability.otlp_endpoint"),
        ({"logging": {"level": "TRACE"}}, "logging.level"),
    ],
)
def test_semantic_validation(settings_env: Path, overrides: dict[str, Any], loc: str) -> None:
    assert _error_locs(overrides) == {loc}


def test_settings_are_immutable() -> None:
    settings = RoboProbeSettings()
    with pytest.raises(ValidationError):
        settings.env = "prod"  # type: ignore[misc]
    with pytest.raises(ValidationError):
        settings.runner.tick_interval_s = 2  # type: ignore[misc]


def test_direct_construction_ignores_environment(
    settings_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROBOPROBE_WORKER__CONCURRENCY", "7")
    assert RoboProbeSettings().worker.concurrency == 1


def test_api_section_validates_standalone() -> None:
    with pytest.raises(ValidationError):
        ApiSettings(host="192.0.2.10")
