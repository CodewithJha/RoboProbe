"""``roboprobe report`` — offline HTML reports (docs/05 §11).

Implements: T-078b, T-079, FR-DSH-007, FR-EXP-003
"""

from __future__ import annotations

from pathlib import Path
from typing import Annotated, cast
from uuid import UUID

import typer

from roboprobe.bootstrap import build_cli_services
from roboprobe.cli._context import get_state
from roboprobe.core.errors import NotFoundError
from roboprobe.reporting.campaign import render_campaign_report
from roboprobe.reporting.experiment import render_experiment_report
from roboprobe.reporting.ports import ReportArtifactStore, ReportUnitOfWork

__all__ = ["app"]

app = typer.Typer(name="report", help="Render offline HTML reports.", invoke_without_command=True)


@app.callback()
def report_cmd(
    ctx: typer.Context,
    report_id: Annotated[UUID, typer.Argument(help="Campaign or experiment id.")],
    output: Annotated[Path, typer.Option("-o", "--output", help="Destination HTML path.")],
) -> None:
    """Render a campaign or experiment report to ``output``."""
    state = get_state(ctx)
    settings = state.bootstrap()
    services = build_cli_services(settings)
    uow = cast(ReportUnitOfWork, services.make_uow())
    store = cast(ReportArtifactStore, services.infra.artifact_store)
    try:
        with uow:
            if uow.campaigns.get(report_id) is not None:
                path = render_campaign_report(
                    report_id,
                    uow,
                    store,
                    out=output,
                    settings=settings.reporting,
                )
                kind = "campaign"
            elif uow.experiments.get(report_id) is not None:
                path = render_experiment_report(
                    report_id,
                    uow,
                    store,
                    out=output,
                    settings=settings.reporting,
                    experiment_settings=settings.experiments,
                )
                kind = "experiment"
            else:
                msg = "id is neither a campaign nor an experiment"
                raise NotFoundError(msg, context={"id": str(report_id)})
    finally:
        services.close()
    state.output.data({"kind": kind, "path": str(path)})
