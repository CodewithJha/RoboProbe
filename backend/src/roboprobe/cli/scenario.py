"""``roboprobe scenario export`` — regression scenario files (UC-07).

Layer: Interface (L4).

Implements: T-045c, FR-SCN-008
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer

from roboprobe.bootstrap import build_cli_services
from roboprobe.cli._context import get_state
from roboprobe.cli.space import REPO_ROOT
from roboprobe.core.clock import SystemClock
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.types import FailureClass, Scenario, Verdict
from roboprobe.scenario.regression import (
    RegressionExpect,
    RegressionProvenance,
    export_regression,
)
from roboprobe.scenario.space import ScenarioSpace

__all__ = ["app"]

app = typer.Typer(name="scenario", help="Regression scenario helpers.", no_args_is_help=True)


def _parse_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        msg = f"invalid run id: {value}"
        raise ValidationError(msg, context={"run_id": value}) from exc


@app.command("export")
def export_cmd(
    ctx: typer.Context,
    run_id: Annotated[str, typer.Argument()],
    output: Annotated[
        Path | None, typer.Option("-o", "--output", help="Destination YAML path.")
    ] = None,
) -> None:
    """Export a finished run as a regression scenario YAML."""
    state = get_state(ctx)
    settings = state.bootstrap()
    services = build_cli_services(settings)
    rid = _parse_id(run_id)
    try:
        with services.make_uow() as uow:
            run = uow.runs.get(rid)
            if run is None:
                msg = "run not found"
                raise NotFoundError(msg, context={"run_id": run_id})
            campaign = uow.campaigns.get(run.campaign_id)
            if campaign is None:
                msg = "campaign not found"
                raise NotFoundError(msg)
        space = ScenarioSpace.from_yaml(
            REPO_ROOT / "configs" / "scenario_spaces" / f"{campaign.space_id}.yaml",
            base_dir=REPO_ROOT,
        )
        scenario = Scenario(
            space_id=space.id,
            space_version=space.version,
            values=dict(run.scenario_values),
            scenario_hash=run.scenario_hash,
        )
        expect = None
        if run.verdict is not None:
            fc = None
            if run.primary_failure is not None:
                raw = getattr(run.primary_failure, "value", run.primary_failure)
                fc = FailureClass(str(raw))
            expect = RegressionExpect(
                verdict=Verdict(str(getattr(run.verdict, "value", run.verdict))),
                failure_class=fc,
            )
        text = export_regression(
            scenario,
            seed=run.seed,
            provenance=RegressionProvenance(source_run=rid, exported_at=SystemClock().now()),
            expect=expect,
        )
        dest = output if output is not None else Path(f"scenario-{run_id}.yaml")
        dest.write_text(text, encoding="utf-8")
        state.output.data({"run_id": run_id, "path": str(dest)})
    finally:
        services.close()
