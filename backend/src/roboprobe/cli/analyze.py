"""``roboprobe analyze <campaign_id>`` — on-demand campaign analysis.

Store adapters are loaded via ``importlib`` (docs/16 §2, T-046).

Implements: T-075b, FR-ANA-006
"""

from __future__ import annotations

import importlib
from concurrent.futures import ThreadPoolExecutor
from typing import Annotated, Literal
from uuid import UUID

import typer

from roboprobe.analysis.base import AnalysisKind
from roboprobe.bootstrap import build_cli_services
from roboprobe.cli._context import get_state
from roboprobe.cli.space import REPO_ROOT
from roboprobe.core.clock import SystemClock
from roboprobe.core.errors import ValidationError
from roboprobe.runner.analysis_jobs import AnalysisJobRunner

__all__ = ["app"]

app = typer.Typer(
    name="analyze",
    help="Run failure analysis for a campaign.",
    invoke_without_command=True,
)


def _parse_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        msg = f"invalid campaign id: {value}"
        raise ValidationError(msg, context={"campaign_id": value}) from exc


@app.callback(invoke_without_command=True)
def analyze_cmd(
    ctx: typer.Context,
    campaign_id: Annotated[str, typer.Argument(help="Campaign UUID.")],
    kind: Annotated[
        Literal["full", "incremental"], typer.Option("--kind", help="Analysis step chain.")
    ] = "full",
    wait: Annotated[bool, typer.Option("--wait", help="Wait for analysis to finish.")] = False,
) -> None:
    """Enqueue or run analysis for ``campaign_id``."""
    if ctx.invoked_subcommand is not None:
        return
    state = get_state(ctx)
    settings = state.bootstrap()
    services = build_cli_services(settings)
    cid = _parse_id(campaign_id)
    analysis_kind = AnalysisKind.FULL if kind == "full" else AnalysisKind.INCREMENTAL
    artifacts_mod = importlib.import_module("roboprobe.store.artifacts")
    store = artifacts_mod.LocalArtifactStore(settings.storage.artifact_root)
    max_workers = settings.runner.analysis.max_workers
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        runner = AnalysisJobRunner(
            services.uow_factory,
            store,
            settings,
            executor,
            SystemClock(),
            campaigns=services.campaigns,
            engine=services.infra.engine,
            space_root=REPO_ROOT,
        )
        if wait:
            analysis_id = runner.request(cid, analysis_kind)
            state.output.data(
                {
                    "campaign_id": str(cid),
                    "analysis_id": str(analysis_id),
                    "kind": kind,
                    "waited": True,
                }
            )
            return
        future = runner.schedule(cid, analysis_kind, complete_campaign=False)
        state.output.data(
            {
                "campaign_id": str(cid),
                "kind": kind,
                "scheduled": future is not None,
                "waited": False,
            }
        )
