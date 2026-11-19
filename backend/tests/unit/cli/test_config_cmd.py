"""CliRunner tests for ``roboprobe config show`` with env/TOML/secret fixtures (docs/27 §2)."""

from __future__ import annotations

import json
import logging
from pathlib import Path

import pytest
from typer.testing import CliRunner

from roboprobe.cli.main import ExitCode, app

pytestmark = pytest.mark.unit

TOKEN = "dummy-token-value"
MASK = "**********"

runner = CliRunner()


def _show(*args: str) -> dict[str, object]:
    result = runner.invoke(app, ["--json", "config", "show", *args])
    assert result.exit_code == ExitCode.OK, result.output
    payload: dict[str, object] = json.loads(result.stdout)
    return payload


def test_show_lists_every_key_with_secrets_masked(
    settings_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROBOPROBE_API__TOKEN", TOKEN)
    values = _show()
    assert values["api.token"] == MASK
    assert values["database.url"] == MASK
    assert values["logging.level"] == "INFO"
    assert "oracles.loc.e_max" in values
    assert TOKEN not in json.dumps(values)


def test_sources_report_where_each_value_came_from(
    settings_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    (settings_env / "roboprobe.toml").write_text("[worker]\nconcurrency = 3\n", encoding="utf-8")
    (settings_env / ".env").write_text("ROBOPROBE_API__PORT=8100\n", encoding="utf-8")
    (settings_env / "secrets" / "api_token").write_text(TOKEN, encoding="utf-8")
    monkeypatch.setenv("ROBOPROBE_RUNNER__MAX_BUDGET", "77")

    result = runner.invoke(app, ["--json", "--log-level", "debug", "config", "show", "--sources"])
    assert result.exit_code == ExitCode.OK, result.output
    shown = json.loads(result.stdout)

    assert shown["worker.concurrency"] == {"value": 3, "source": "toml:roboprobe.toml"}
    assert shown["api.port"] == {"value": 8100, "source": ".env"}
    assert shown["api.token"] == {"value": MASK, "source": "secrets"}
    assert shown["runner.max_budget"] == {"value": 77, "source": "env"}
    assert shown["logging.level"] == {"value": "DEBUG", "source": "cli"}
    assert shown["api.host"]["source"] == "default"
    assert TOKEN not in result.output


def test_config_flag_selects_the_toml_file(settings_env: Path) -> None:
    custom = settings_env / "lab.toml"
    custom.write_text("[worker]\nconcurrency = 5\n", encoding="utf-8")
    (settings_env / "roboprobe.toml").write_text("[worker]\nconcurrency = 2\n", encoding="utf-8")
    result = runner.invoke(app, ["--json", "--config", str(custom), "config", "show", "--sources"])
    assert result.exit_code == ExitCode.OK, result.output
    assert json.loads(result.stdout)["worker.concurrency"] == {
        "value": 5,
        "source": f"toml:{custom}",
    }


def test_table_output_shows_keys_values_and_sources(
    settings_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROBOPROBE_API__TOKEN", TOKEN)
    monkeypatch.setenv("COLUMNS", "200")
    plain = runner.invoke(app, ["config", "show"])
    with_sources = runner.invoke(app, ["config", "show", "--sources"])
    assert plain.exit_code == with_sources.exit_code == ExitCode.OK
    assert "api.token" in plain.stdout
    assert MASK in plain.stdout
    assert "source" not in plain.stdout
    assert "source" in with_sources.stdout
    assert "default" in with_sources.stdout
    assert TOKEN not in plain.stdout + with_sources.stdout


def test_invalid_config_exits_2_with_readable_errors(
    settings_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROBOPROBE_WORKER__CONCURRENCY", "-3")
    monkeypatch.setenv("COLUMNS", "200")
    result = runner.invoke(app, ["config", "show"])
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert result.stdout == ""
    assert "CONFIG_INVALID" in result.stderr
    assert "loc=worker.concurrency" in result.stderr
    assert "-3" not in result.stderr  # input values are never echoed (may be secrets)


def test_invalid_config_json_error_lists_each_problem(
    settings_env: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("ROBOPROBE_WORKER__CONCURRENCY", "-3")
    result = runner.invoke(app, ["--json", "config", "show"])
    assert result.exit_code == ExitCode.USAGE_ERROR
    error = json.loads(result.stderr)["error"]
    assert error["code"] == "CONFIG_INVALID"
    assert [e["loc"] for e in error["context"]["errors"]] == ["worker.concurrency"]


def test_config_loaded_event_carries_sources_not_values(
    settings_env: Path, monkeypatch: pytest.MonkeyPatch, caplog: pytest.LogCaptureFixture
) -> None:
    monkeypatch.setenv("ROBOPROBE_API__TOKEN", TOKEN)
    with caplog.at_level(logging.INFO, logger="roboprobe.cli.config"):
        _show()
    (record,) = [r for r in caplog.records if r.getMessage() == "config.loaded"]
    assert record.sources == ["default", "env"]  # type: ignore[attr-defined]
    assert TOKEN not in caplog.text


def test_group_without_subcommand_shows_help() -> None:
    result = runner.invoke(app, ["config"])
    assert "show" in result.output
