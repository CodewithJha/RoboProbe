import re
import shutil
from pathlib import Path

import pytest

from roboprobe.core.errors import ConfigError
from roboprobe.core.settings import RoboProbeSettings, explain_sources, load_settings

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
KEY = "runner.max_budget"
DEFAULT_BUDGET = RoboProbeSettings().runner.max_budget


def _write_layers(cwd: Path, monkeypatch: pytest.MonkeyPatch, layers: set[str]) -> None:
    if "toml" in layers:
        (cwd / "roboprobe.toml").write_text("[runner]\nmax_budget = 10\n")
    if "dotenv" in layers:
        (cwd / ".env").write_text("ROBOPROBE_RUNNER__MAX_BUDGET=20\n")
    if "env" in layers:
        monkeypatch.setenv("ROBOPROBE_RUNNER__MAX_BUDGET", "30")


@pytest.mark.parametrize(
    ("layers", "expected", "source"),
    [
        ({"cli", "env", "dotenv", "toml"}, 40, "cli"),
        ({"env", "dotenv", "toml"}, 30, "env"),
        ({"dotenv", "toml"}, 20, ".env"),
        ({"toml"}, 10, "toml:roboprobe.toml"),
        (set(), DEFAULT_BUDGET, "default"),
    ],
)
def test_precedence_each_layer_removed_yields_next(
    settings_env: Path,
    monkeypatch: pytest.MonkeyPatch,
    layers: set[str],
    expected: int,
    source: str,
) -> None:
    _write_layers(settings_env, monkeypatch, layers)
    cli = {KEY: 40} if "cli" in layers else None
    settings = load_settings(cli)
    assert settings.runner.max_budget == expected
    assert explain_sources(settings)[KEY] == source


def test_defaults_without_any_source(settings_env: Path) -> None:
    settings = load_settings()
    assert settings.model_dump() == RoboProbeSettings().model_dump()
    assert set(explain_sources(settings).values()) == {"default"}


def test_explicit_config_file_wins_over_cwd_file(
    settings_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (settings_env / "roboprobe.toml").write_text("[worker]\nconcurrency = 2\n")
    other = settings_env / "other.toml"
    other.write_text("[worker]\nconcurrency = 3\n")
    monkeypatch.setenv("ROBOPROBE_CONFIG_FILE", str(other))
    settings = load_settings()
    assert settings.worker.concurrency == 3
    assert explain_sources(settings)["worker.concurrency"] == f"toml:{other}"


def test_missing_explicit_config_file_fails(
    settings_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROBOPROBE_CONFIG_FILE", str(settings_env / "nope.toml"))
    with pytest.raises(ConfigError, match="missing file"):
        load_settings()


def test_config_file_argument_wins_over_env_variable(
    settings_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from_env = settings_env / "env.toml"
    from_env.write_text("[worker]\nconcurrency = 3\n")
    from_arg = settings_env / "arg.toml"
    from_arg.write_text("[worker]\nconcurrency = 4\n")
    monkeypatch.setenv("ROBOPROBE_CONFIG_FILE", str(from_env))
    settings = load_settings(config_file=from_arg)
    assert settings.worker.concurrency == 4
    assert explain_sources(settings)["worker.concurrency"] == f"toml:{from_arg}"
    with pytest.raises(ConfigError, match="config file points to a missing file"):
        load_settings(config_file=settings_env / "nope.toml")


def test_nested_env_and_json_values(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROBOPROBE_ORACLES__LOC__E_MAX", "0.4")
    monkeypatch.setenv("ROBOPROBE_API__CORS_ORIGINS", '["http://example.test"]')
    settings = load_settings()
    assert settings.oracles.loc.e_max == 0.4
    assert settings.api.cors_origins == ("http://example.test",)


def test_env_aliases_and_canonical_name_wins(
    settings_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    alias_url = "postgresql+psycopg://alias@db:5432/rp"
    monkeypatch.setenv("ROBOPROBE_DATABASE_URL", alias_url)
    monkeypatch.setenv("ROBOPROBE_API_TOKEN", "alias-token")
    settings = load_settings()
    assert settings.database.url.get_secret_value() == alias_url
    assert settings.api.token is not None
    assert settings.api.token.get_secret_value() == "alias-token"

    canonical_url = "postgresql+psycopg://canonical@db:5432/rp"
    monkeypatch.setenv("ROBOPROBE_DATABASE__URL", canonical_url)
    assert load_settings().database.url.get_secret_value() == canonical_url


def test_cli_overrides_accept_nested_and_dotted_keys(settings_env: Path) -> None:
    settings = load_settings({"worker": {"concurrency": 4}, "oracles.loc.e_max": 0.3})
    assert settings.worker.concurrency == 4
    assert settings.oracles.loc.e_max == 0.3
    sources = explain_sources(settings)
    assert sources["worker.concurrency"] == sources["oracles.loc.e_max"] == "cli"


def test_dotenv_tolerates_compose_variables(settings_env: Path) -> None:
    (settings_env / ".env").write_text("ROBOPROBE_IMAGE_TAG=dev\nROBOPROBE_WORKER__CONCURRENCY=2\n")
    assert load_settings().worker.concurrency == 2


def test_empty_env_values_are_ignored(settings_env: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setenv("ROBOPROBE_API_TOKEN", "")
    monkeypatch.setenv("ROBOPROBE_WORKER__CONCURRENCY", "")
    settings = load_settings()
    assert settings.api.token is None
    assert settings.worker.concurrency == 1


@pytest.mark.parametrize("template", ["roboprobe.example.toml", ".env.example"])
def test_repository_templates_load_cleanly(settings_env: Path, template: str) -> None:
    target = "roboprobe.toml" if template.endswith(".toml") else ".env"
    shutil.copy(REPO_ROOT / template, settings_env / target)
    load_settings()


def test_uncommented_example_toml_round_trips_defaults(settings_env: Path) -> None:
    lines = (REPO_ROOT / "roboprobe.example.toml").read_text().splitlines()
    key_line = re.compile(r"^# [a-z0-9_]+ = (?!\.\.\.)(?!\s*\()")
    active = [line.removeprefix("# ") if key_line.match(line) else line for line in lines]
    (settings_env / "roboprobe.toml").write_text("\n".join(active) + "\n")
    settings = load_settings()
    assert settings.model_dump(exclude={"worker": {"id_prefix"}}) == RoboProbeSettings().model_dump(
        exclude={"worker": {"id_prefix"}}
    )


def test_alias_field_explained_by_alias(settings_env: Path) -> None:
    (settings_env / "roboprobe.toml").write_text("[analysis.feature_weights]\nclass = 0.5\n")
    settings = load_settings()
    assert settings.analysis.feature_weights.class_ == 0.5
    assert explain_sources(settings)["analysis.feature_weights.class"].startswith("toml:")
