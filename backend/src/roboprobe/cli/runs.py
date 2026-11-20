"""``roboprobe runs`` / ``queue`` helpers (runbook RB-05).

Layer: Interface (L4).

Implements: T-045b, FR-CLI-001
"""

from __future__ import annotations

from typing import Annotated

import typer

from roboprobe.bootstrap import build_cli_services, build_orchestrator
from roboprobe.cli._context import get_state
from roboprobe.core.errors import ValidationError
from roboprobe.core.types import RunStatus

__all__ = ["app", "queue_app"]

app = typer.Typer(name="runs", help="Run maintenance helpers.", no_args_is_help=True)
queue_app = typer.Typer(name="queue", help="Queue depth helpers.", no_args_is_help=True)


@app.command("requeue")
def requeue_cmd(
    ctx: typer.Context,
    stuck: Annotated[
        bool, typer.Option("--stuck", help="Requeue CLAIMED/RUNNING with dead workers.")
    ] = False,
) -> None:
    """Requeue stuck runs (delegates to the reaper sweep)."""
    if not stuck:
        msg = "pass --stuck (only supported mode)"
        raise ValidationError(msg)
    state = get_state(ctx)
    settings = state.bootstrap()
    orch = build_orchestrator(settings)
    try:
        n = orch.reaper.reap()
        state.output.data({"requeued_or_failed": n})
    finally:
        orch.close()


@queue_app.command("stats")
def queue_stats_cmd(ctx: typer.Context) -> None:
    """Show PENDING run counts per backend."""
    state = get_state(ctx)
    settings = state.bootstrap()
    services = build_cli_services(settings)
    try:
        counts: dict[str, int] = {}
        with services.make_uow() as uow:
            page = uow.campaigns.list(limit=500)
            for campaign in page.items:
                cursor = None
                while True:
                    runs = uow.runs.list_for_campaign(campaign.id, limit=None, cursor=cursor)
                    for run in runs.items:
                        status = RunStatus(str(getattr(run.status, "value", run.status)))
                        if status is RunStatus.PENDING:
                            counts[run.backend] = counts.get(run.backend, 0) + 1
                    cursor = runs.next_cursor
                    if cursor is None:
                        break
        rows: list[list[str | int]] = [
            [backend, count] for backend, count in sorted(counts.items())
        ]
        state.output.table(["backend", "pending"], rows, title="Queue depth")
    finally:
        services.close()
