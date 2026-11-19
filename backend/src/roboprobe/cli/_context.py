"""Per-invocation CLI state created by the root callback and shared with every command group.

Layer: Interface (L4).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path

import typer

from roboprobe.cli._output import Output

__all__ = ["CliState", "LogLevel", "get_state"]


class LogLevel(StrEnum):
    """Log levels accepted by ``--log-level`` (case-insensitive)."""

    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass(frozen=True, slots=True)
class CliState:
    """Global options resolved once per invocation.

    Attributes:
        output: Presentation helper honouring ``--json``.
        config_file: Explicit TOML config path (``--config``); ``None`` defers to settings
            discovery (docs/27 §2).
        log_level: Explicit log level (``--log-level``); ``None`` defers to settings.
    """

    output: Output
    config_file: Path | None = None
    log_level: LogLevel | None = None


def get_state(ctx: typer.Context) -> CliState:
    """Return the :class:`CliState` stored by the root callback.

    Args:
        ctx: The current Typer context (sub-commands inherit the root object).

    Raises:
        TypeError: If called outside a ``roboprobe`` invocation (programming error).
    """
    state = ctx.find_object(CliState)
    if state is None:
        msg = "CLI state missing: commands must run under the roboprobe root app"
        raise TypeError(msg)
    return state
