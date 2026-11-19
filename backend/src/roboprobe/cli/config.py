"""``roboprobe config``: inspect the configuration a process resolves (docs/27 §2, docs/30 §1).

Secrets are masked (``SecretStr`` fields render as ``**********``) and the ``config.loaded``
event carries source labels only, never values (docs/34 §6).

Layer: Interface (L4).
"""

from __future__ import annotations

import logging
from typing import Annotated

import typer
from pydantic import JsonValue

from roboprobe.cli._context import get_state
from roboprobe.core.settings import explain_sources, flatten

__all__ = ["app"]

app = typer.Typer(name="config", help="Inspect the resolved configuration.", no_args_is_help=True)

_log = logging.getLogger(__name__)

KEY_COLUMN = "key"
VALUE_COLUMN = "value"
SOURCE_COLUMN = "source"


@app.command("show")
def show(
    ctx: typer.Context,
    sources: Annotated[
        bool, typer.Option("--sources", help="Also show which source set each value.")
    ] = False,
) -> None:
    """Print every resolved setting as a dotted key (secrets masked)."""
    state = get_state(ctx)
    settings = state.load_settings()
    provenance = explain_sources(settings)
    _log.info("config.loaded", extra={"sources": sorted(set(provenance.values()))})

    values: dict[str, JsonValue] = dict(flatten(settings.model_dump(mode="json", by_alias=True)))
    keys = sorted(values)
    if state.output.json_mode:
        payload: dict[str, JsonValue] = (
            {key: {VALUE_COLUMN: values[key], SOURCE_COLUMN: provenance[key]} for key in keys}
            if sources
            else {key: values[key] for key in keys}
        )
        state.output.data(payload)
        return
    columns = [KEY_COLUMN, VALUE_COLUMN, *([SOURCE_COLUMN] if sources else [])]
    rows: list[list[JsonValue]] = [
        [key, values[key], *([provenance[key]] if sources else [])] for key in keys
    ]
    state.output.table(columns, rows, title="RoboProbe configuration")
