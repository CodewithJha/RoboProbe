"""``roboprobe reference generate|label`` (T-103, MET-02/08).

Implements: FR-CLI-001
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated

import pyarrow.parquet as pq
import typer

from roboprobe.backends.kinematic2d.calibration import load_calibration
from roboprobe.backends.kinematic2d.model import Kinematic2DModel
from roboprobe.cli._context import get_state
from roboprobe.cli.space import REPO_ROOT
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.experiments.reference_set import (
    ReferenceManifest,
    generate_rows,
    label_rows,
    sha256_file,
    write_manifest,
    write_parquet,
)
from roboprobe.scenario.space import ScenarioSpace

__all__ = ["app"]

app = typer.Typer(
    name="reference",
    help="k2d reference set tools (MET-02/08).",
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
    ref = settings.experiments.reference_set
    count = n if n is not None else ref.n
    ref_seed = seed if seed is not None else ref.seed
    space = ScenarioSpace.from_yaml(
        REPO_ROOT / "configs" / "scenario_spaces" / f"{space_id}.yaml",
        base_dir=REPO_ROOT,
    )
    work = Path(settings.storage.workdir_root) / "reference-generate"
    rows = generate_rows(
        space, settings, n=count, seed=ref_seed, repo_root=REPO_ROOT, workdir=work
    )
    write_parquet(output, rows)
    model = Kinematic2DModel.from_yaml(Path(settings.backends.kinematic2d.model_file))
    manifest = ReferenceManifest(
        path=str(output),
        sha256=sha256_file(output),
        n=count,
        seed=ref_seed,
        space_id=space.id,
        space_version=space.version,
        k2d_model_version=model.id,
    )
    write_manifest(output.with_suffix(".manifest.json"), manifest)
    state.output.data(manifest.__dict__)


@app.command("label")
def reference_label(
    ctx: typer.Context,
    source: Annotated[Path, typer.Argument(help="Reference parquet to label.")],
    output: Annotated[Path | None, typer.Option("--output", help="Defaults to in-place.")] = None,
) -> None:
    """Label failing reference rows with nearest GT mode (docs/19 §3)."""
    state = get_state(ctx)
    settings: RoboProbeSettings = state.bootstrap()
    calibration = load_calibration(Path(settings.backends.kinematic2d.calibration_file))
    table = pq.read_table(source)
    rows = table.to_pylist()
    label_rows(rows, calibration, radius=settings.experiments.mode_match_radius)
    dest = output or source
    write_parquet(dest, rows)
    labelled = sum(1 for row in rows if row.get("gt_label"))
    state.output.data({"path": str(dest), "labelled_failures": labelled})
