"""Unit tests for the ``roboprobe`` root app and its exit-code contract (docs/05 §11)."""

from __future__ import annotations

import json
from collections.abc import Callable
from importlib.metadata import version
from pathlib import Path
from typing import get_args

import pytest
import typer
from typer.testing import CliRunner

from roboprobe.cli._context import CliState, LogLevel, get_state
from roboprobe.cli._output import Output
from roboprobe.cli.main import (
    COMMAND_GROUPS,
    CONFIG_FILE_ENV,
    ExitCode,
    app,
    create_app,
    exit_code_for,
)
from roboprobe.core import errors
from roboprobe.core.settings.observability import LogLevel as SettingsLogLevel

pytestmark = pytest.mark.unit

# Plain help text whatever the caller's terminal: Typer forces a Rich terminal under
# GITHUB_ACTIONS or FORCE_COLOR, and TERM=dumb makes Rich emit no ANSI styling.
runner = CliRunner(env={"TERM": "dumb", "NO_COLOR": "1"})


def _probe_app(action: Callable[[CliState], None]) -> typer.Typer:
    """Root app with a ``probe run`` command that executes ``action`` with the CLI state."""
    probe = typer.Typer(name="probe")

    @probe.command("run")
    def run(ctx: typer.Context) -> None:
        action(get_state(ctx))

    @probe.command("noop")
    def noop() -> None:
        """Keep ``probe`` a group so ``probe run`` resolves as a sub-command."""

    return create_app([probe])


def _raise(exc: Exception) -> Callable[[CliState], None]:
    def action(_state: CliState) -> None:
        raise exc

    return action


def test_help_lists_global_options() -> None:
    result = runner.invoke(app, ["--help"])
    assert result.exit_code == ExitCode.OK
    for option in ("--config", "--log-level", "--json", "--version"):
        assert option in result.output


def test_version_prints_installed_distribution_version() -> None:
    result = runner.invoke(app, ["--version"])
    assert result.exit_code == ExitCode.OK
    assert result.output.strip() == f"roboprobe {version('roboprobe')}"


def test_no_command_shows_help_as_usage_error() -> None:
    result = runner.invoke(app, [])
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert "Usage" in result.output


def test_unknown_option_is_a_usage_error() -> None:
    assert runner.invoke(app, ["--bogus"]).exit_code == ExitCode.USAGE_ERROR


def test_success_exits_zero_and_renders_data() -> None:
    result = runner.invoke(_probe_app(lambda s: s.output.data({"ok": True})), ["probe", "run"])
    assert result.exit_code == ExitCode.OK
    assert "ok" in result.output


@pytest.mark.parametrize(
    ("exc", "expected"),
    [
        (errors.ValidationError("bad space"), ExitCode.USAGE_ERROR),
        (errors.ConfigError("bad config"), ExitCode.USAGE_ERROR),
        (errors.BackendError("sim crashed"), ExitCode.RUNTIME_ERROR),
        (errors.RoboProbeError("boom"), ExitCode.RUNTIME_ERROR),
    ],
)
def test_roboprobe_errors_map_to_exit_codes(exc: errors.RoboProbeError, expected: ExitCode) -> None:
    assert exit_code_for(exc) == expected
    result = runner.invoke(_probe_app(_raise(exc)), ["probe", "run"])
    assert result.exit_code == expected
    assert f"[{exc.code}] {exc.message}" in result.stderr


def test_error_in_json_mode_is_structured_on_stderr() -> None:
    exc = errors.ValidationError("bad space", code=errors.ErrorCode.SPACE_INVALID, context={"k": 1})
    result = runner.invoke(_probe_app(_raise(exc)), ["--json", "probe", "run"])
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert result.stdout == ""
    assert json.loads(result.stderr) == {
        "error": {"code": "SPACE_INVALID", "message": "bad space", "context": {"k": 1}}
    }


def test_unexpected_exceptions_propagate_as_bugs() -> None:
    result = runner.invoke(_probe_app(_raise(RuntimeError("bug"))), ["probe", "run"])
    assert result.exit_code == ExitCode.RUNTIME_ERROR
    assert isinstance(result.exception, RuntimeError)


def test_global_options_reach_commands(tmp_path: Path) -> None:
    config = tmp_path / "roboprobe.toml"
    config.write_text("", encoding="utf-8")
    seen: list[CliState] = []
    args = ["--config", str(config), "--log-level", "debug", "--json", "probe", "run"]
    result = runner.invoke(_probe_app(seen.append), args)
    assert result.exit_code == ExitCode.OK
    (state,) = seen
    assert state.config_file == config
    assert state.log_level is LogLevel.DEBUG
    assert state.output.json_mode


def test_config_file_is_read_from_environment(tmp_path: Path) -> None:
    config = tmp_path / "env.toml"
    config.write_text("", encoding="utf-8")
    seen: list[CliState] = []
    result = runner.invoke(
        _probe_app(seen.append), ["probe", "run"], env={CONFIG_FILE_ENV: str(config)}
    )
    assert result.exit_code == ExitCode.OK
    assert seen[0].config_file == config


def test_missing_config_file_is_a_usage_error(tmp_path: Path) -> None:
    seen: list[CliState] = []
    args = ["--config", str(tmp_path / "missing.toml"), "probe", "run"]
    result = runner.invoke(_probe_app(seen.append), args)
    assert result.exit_code == ExitCode.USAGE_ERROR
    assert seen == []


def test_get_state_outside_the_root_app_is_a_programming_error() -> None:
    bare = typer.Typer()

    @bare.command()
    def orphan(ctx: typer.Context) -> None:
        get_state(ctx)

    result = runner.invoke(bare, [])
    assert isinstance(result.exception, TypeError)
    assert "CLI state missing" in str(result.exception)


def test_output_table_renders_rich_and_json(capsys: pytest.CaptureFixture[str]) -> None:
    Output().table(["id", "name"], [[1, "warehouse_v1"]], title="Spaces")
    assert "warehouse_v1" in capsys.readouterr().out
    Output(json_mode=True).table(["id", "name"], [[1, "warehouse_v1"]])
    assert json.loads(capsys.readouterr().out) == [{"id": 1, "name": "warehouse_v1"}]


def test_output_table_rejects_ragged_rows() -> None:
    with pytest.raises(ValueError, match="zip"):
        Output(json_mode=True).table(["id", "name"], [[1]])


def test_output_data_json_is_compact_and_sorted(capsys: pytest.CaptureFixture[str]) -> None:
    Output(json_mode=True).data({"b": 1, "a": [1, 2]})
    assert capsys.readouterr().out == '{"a": [1, 2], "b": 1}\n'


def test_output_json_escapes_non_ascii(capsys: pytest.CaptureFixture[str]) -> None:
    Output(json_mode=True).data({"label": "Lagerhalle Süd"})
    out = capsys.readouterr().out
    assert out.isascii()
    assert json.loads(out) == {"label": "Lagerhalle Süd"}


def test_cli_log_levels_match_the_settings_vocabulary() -> None:
    assert {level.value for level in LogLevel} == set(get_args(SettingsLogLevel))


def test_registered_groups_have_unique_names_and_appear_in_help() -> None:
    names = [group.info.name for group in COMMAND_GROUPS]
    assert all(names)
    assert len(set(names)) == len(names)
    help_text = runner.invoke(app, ["--help"]).output
    assert all(str(name) in help_text for name in names)


def test_human_error_renders_scalar_and_list_context(capsys: pytest.CaptureFixture[str]) -> None:
    exc = errors.ValidationError(
        "bad", context={"field": "x", "errors": [{"loc": "a", "msg": "m"}]}
    )
    Output().error(exc)
    err = capsys.readouterr().err
    assert "  field:\n    - x" in err
    assert "    - loc=a, msg=m" in err


def test_table_renders_non_string_cells_as_json(capsys: pytest.CaptureFixture[str]) -> None:
    Output().table(["k", "v"], [["none", None], ["flag", True], ["list", ["a", 1]]])
    out = capsys.readouterr().out
    assert "null" in out
    assert "true" in out
    assert '["a", 1]' in out
