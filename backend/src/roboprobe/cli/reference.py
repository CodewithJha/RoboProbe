"""``roboprobe reference generate|label|score`` (MET-02/08/09).

Implements: FR-CLI-001
"""

from __future__ import annotations

from dataclasses import asdict
from pathlib import Path
from typing import Annotated

import typer

from roboprobe.bootstrap.reference_scoring import score_reference
from roboprobe.bootstrap.reference_set import generate_and_write, label_parquet
from roboprobe.cli._context import get_state
from roboprobe.core.settings import RoboProbeSettings

__all__ = ["app"]

app = typer.Typer(
    name="reference",
    help="k2d reference set tools (MET-02/08/09).",
    no_args_is_help=True,
)


@app.command("generate")
def reference_generate(
    ctx: typer.Context,
    output: Annotated[Path, typer.Option("--output", help="Parquet output path.")],
    n: Annotated[int | None, typer.Option("--n", help="Override reference size.")] = None,
    seed: Annotated[int | None, typer.Option("--seed")] = None,
    space_id: Annotated[str, typer.Option("--space")] = "warehouse_v1",
) -> None:
    """Sample Sobol scenarios, run kinematic2d once each, write Parquet + manifest."""
    state = get_state(ctx)
    settings: RoboProbeSettings = state.bootstrap()
    manifest = generate_and_write(settings, output=output, n=n, seed=seed, space_id=space_id)
    state.output.data(asdict(manifest))


@app.command("label")
def reference_label(
    ctx: typer.Context,
    source: Annotated[Path, typer.Argument(help="Reference parquet to label.")],
    output: Annotated[Path | None, typer.Option("--output", help="Defaults to in-place.")] = None,
    reviewed_labels: Annotated[
        Path | None, typer.Option("--reviewed-labels", help="JSON reviewed mode assignments.")
    ] = None,
) -> None:
    """Label failing reference rows from review or calibrated modes (docs/19 §3)."""
    state = get_state(ctx)
    settings: RoboProbeSettings = state.bootstrap()
    dest, labelled = label_parquet(settings, source, output=output, reviewed_labels=reviewed_labels)
    state.output.data({"path": str(dest), "labelled_failures": labelled})


@app.command("score")
def reference_score(
    ctx: typer.Context,
    raw: Annotated[Path, typer.Argument(help="EXP-07 raw runs Parquet.")],
    run_manifest: Annotated[Path, typer.Option("--run-manifest", help="Run provenance manifest.")],
    reference: Annotated[Path, typer.Option("--reference", help="Original reference Parquet.")],
    reviewed_labels: Annotated[
        Path | None, typer.Option("--reviewed-labels", help="JSON reviewed mode dispositions.")
    ] = None,
) -> None:
    """Recompute EXP-07 MET-02/09 per strategy and replicate from reviewed evidence."""
    get_state(ctx).output.data(score_reference(raw, run_manifest, reference, reviewed_labels))
