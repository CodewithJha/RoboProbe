"""``roboprobe`` console entry point: root Typer app, global options and the exit-code contract.

Exit codes (docs/05 §11): ``0`` success, ``1`` runtime error, ``2`` validation/usage error
(:class:`~roboprobe.core.errors.ConfigError`, :class:`~roboprobe.core.errors.ValidationError`,
bad CLI usage), ``3`` campaign finished with failures (only with ``--fail-on-failure``).

Adding a command group takes one import and one list entry:

1. Create ``roboprobe/cli/<group>.py`` exposing ``app = typer.Typer(name="<group>", help=...)``;
   commands read global options with ``get_state(ctx)`` and print only through ``Output``.
2. Import it below and append ``<group>.app`` to :data:`COMMAND_GROUPS`.

Until the CLI composition root exists (T-046), commands build what they need from settings.

Layer: Interface (L4).

Implements: docs/05 §11
"""

from __future__ import annotations

from collections.abc import Sequence
from enum import IntEnum
from importlib.metadata import version
from pathlib import Path
from typing import Annotated, Any

import typer
from typer.core import TyperGroup

from roboprobe.cli import artifacts, config
from roboprobe.cli._context import DISTRIBUTION_NAME, CliState, LogLevel
from roboprobe.cli._output import Output
from roboprobe.core.errors import ConfigError, RoboProbeError, ValidationError

__all__ = [
    "COMMAND_GROUPS",
    "CONFIG_FILE_ENV",
    "DISTRIBUTION_NAME",
    "LOG_LEVEL_ENV",
    "ExitCode",
    "app",
    "create_app",
    "exit_code_for",
]

CONFIG_FILE_ENV = "ROBOPROBE_CONFIG_FILE"
LOG_LEVEL_ENV = "ROBOPROBE_LOGGING__LEVEL"

COMMAND_GROUPS: Sequence[typer.Typer] = (config.app, artifacts.app, artifacts.gc_app)
"""Registered command groups, in ``--help`` order (append-only; see module docstring)."""


class ExitCode(IntEnum):
    """Process exit codes (docs/05 §11). Values are a public contract for CI scripts."""

    OK = 0
    RUNTIME_ERROR = 1
    USAGE_ERROR = 2
    FAILURES_FOUND = 3


def exit_code_for(exc: RoboProbeError) -> ExitCode:
    """Map a RoboProbe error to its exit code: invalid input/config ``2``, anything else ``1``."""
    if isinstance(exc, ConfigError | ValidationError):
        return ExitCode.USAGE_ERROR
    return ExitCode.RUNTIME_ERROR


class _RoboProbeGroup(TyperGroup):
    """Root group that turns :class:`RoboProbeError` into a reported error and an exit code.

    Mapping happens here (not in a ``main()`` wrapper) so it applies equally to the installed
    script and to ``CliRunner``; non-RoboProbe exceptions are bugs and propagate unchanged.
    """

    # ``Any``: the base signature uses Typer's vendored (private) Click ``Context`` type.
    def invoke(self, ctx: Any) -> Any:  # noqa: ANN401
        try:
            return super().invoke(ctx)
        except RoboProbeError as exc:
            state = ctx.find_object(CliState)
            (state.output if state is not None else Output()).error(exc)
            raise typer.Exit(exit_code_for(exc)) from exc


def _print_version(value: bool) -> None:
    if value:
        typer.echo(f"{DISTRIBUTION_NAME} {version(DISTRIBUTION_NAME)}")
        raise typer.Exit(ExitCode.OK)


def _root(
    ctx: typer.Context,
    config_file: Annotated[
        Path | None,
        typer.Option(
            "--config",
            envvar=CONFIG_FILE_ENV,
            exists=True,
            dir_okay=False,
            readable=True,
            help="TOML configuration file (default: ./roboprobe.toml if present).",
        ),
    ] = None,
    log_level: Annotated[
        LogLevel | None,
        typer.Option(
            "--log-level",
            envvar=LOG_LEVEL_ENV,
            case_sensitive=False,
            help="Override the configured log level.",
        ),
    ] = None,
    json_output: Annotated[
        bool, typer.Option("--json", help="Machine-readable JSON output on stdout.")
    ] = False,
    _version: Annotated[
        bool,
        typer.Option(
            "--version",
            callback=_print_version,
            is_eager=True,
            help="Show the version and exit.",
        ),
    ] = False,
) -> None:
    """RoboProbe: intelligent failure discovery for mobile robots."""
    ctx.obj = CliState(
        output=Output(json_mode=json_output), config_file=config_file, log_level=log_level
    )


def create_app(command_groups: Sequence[typer.Typer] = COMMAND_GROUPS) -> typer.Typer:
    """Build the root app with the given command groups (tests inject their own groups).

    Args:
        command_groups: Sub-apps to register, each with its own ``name``.

    Returns:
        The configured root :class:`typer.Typer`.
    """
    root = typer.Typer(
        name=DISTRIBUTION_NAME,
        cls=_RoboProbeGroup,
        no_args_is_help=True,
        pretty_exceptions_show_locals=False,
    )
    root.callback()(_root)
    for group in command_groups:
        root.add_typer(group)
    return root


app = create_app()
"""The installed ``roboprobe`` script (``[project.scripts]``)."""
