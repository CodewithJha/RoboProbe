"""Rich/JSON presentation helpers shared by every CLI command (the only place that prints).

Commands never call ``print`` directly (docs/16 §3): they hand data to :class:`Output`, which
renders it for humans (Rich) or, with the global ``--json`` flag, as machine-readable JSON on
stdout. Errors always go to stderr so stdout stays parseable.

Layer: Interface (L4).
"""

from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass, field

from pydantic import JsonValue
from rich.console import Console
from rich.pretty import Pretty
from rich.table import Table
from rich.text import Text

from roboprobe.core.errors import RoboProbeError

__all__ = ["Output"]


def _stdout_console() -> Console:
    return Console()


def _stderr_console() -> Console:
    return Console(stderr=True)


def _cell(value: JsonValue) -> str:
    """Table cell text: strings verbatim, everything else as JSON (``null``, ``true``, lists)."""
    return value if isinstance(value, str) else json.dumps(value)


def _describe(value: JsonValue) -> str:
    """One-line human rendering of a context value (``k=v, k=v`` for mappings)."""
    if isinstance(value, dict):
        return ", ".join(f"{key}={item}" for key, item in value.items())
    return str(value)


@dataclass(frozen=True, slots=True)
class Output:
    """Renders command results and errors in the mode selected by the global ``--json`` flag.

    Attributes:
        json_mode: Emit compact JSON instead of Rich renderables.
        console: Destination for results (stdout).
        err_console: Destination for errors (stderr).
    """

    json_mode: bool = False
    console: Console = field(default_factory=_stdout_console)
    err_console: Console = field(default_factory=_stderr_console)

    def data(self, payload: JsonValue) -> None:
        """Render an arbitrary JSON-compatible result."""
        if self.json_mode:
            self._emit_json(self.console, payload)
        else:
            self.console.print(Pretty(payload))

    def table(
        self,
        columns: Sequence[str],
        rows: Sequence[Sequence[JsonValue]],
        *,
        title: str | None = None,
    ) -> None:
        """Render tabular results: a Rich table, or a JSON list of ``{column: value}`` objects.

        Raises:
            ValueError: If a row does not have exactly one value per column.
        """
        records: list[JsonValue] = [dict(zip(columns, row, strict=True)) for row in rows]
        if self.json_mode:
            self._emit_json(self.console, records)
            return
        table = Table(title=title)
        for column in columns:
            table.add_column(column, overflow="fold")
        for row in rows:
            table.add_row(*(Text(_cell(value)) for value in row))
        self.console.print(table)

    def error(self, exc: RoboProbeError) -> None:
        """Report a RoboProbe error on stderr with its stable code (and context in JSON mode)."""
        if self.json_mode:
            context: Mapping[str, JsonValue] = exc.context
            payload: JsonValue = {
                "error": {"code": str(exc.code), "message": exc.message, "context": dict(context)}
            }
            self._emit_json(self.err_console, payload)
            return
        line = Text.assemble(("error", "bold red"), f" [{exc.code}] ", exc.message)
        self.err_console.print(line)
        for key, value in exc.context.items():
            self.err_console.print(Text(f"  {key}:"))
            items = value if isinstance(value, list) else [value]
            for item in items:
                self.err_console.print(Text(f"    - {_describe(item)}"))

    @staticmethod
    def _emit_json(console: Console, payload: JsonValue) -> None:
        # Bypass Rich markup/highlighting/wrapping so the output is byte-for-byte valid JSON; ASCII
        # escapes keep it encodable on any terminal or pipe encoding (e.g. cp1252 on Windows).
        console.file.write(json.dumps(payload, sort_keys=True) + "\n")
        console.file.flush()
