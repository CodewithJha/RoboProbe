"""``roboprobe replay <run_id>`` — enqueue and report replay agreement.

Layer: Interface (L4).

Implements: T-044, FR-REP-001
"""

from __future__ import annotations

import time
from typing import Annotated
from uuid import UUID

import typer

from roboprobe.bootstrap import build_cli_services, build_worker
from roboprobe.cli._context import get_state
from roboprobe.cli.space import REPO_ROOT
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.types import RunStatus
from roboprobe.runner.replay import ReplayRequest, enqueue_replays, summarise_agreement
from roboprobe.scenario.space import ScenarioSpace

__all__ = ["app"]

app = typer.Typer(name="replay", help="Replay finished runs.", invoke_without_command=True)


def _parse_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        msg = f"invalid run id: {value}"
        raise ValidationError(msg, context={"run_id": value}) from exc


def _trace_hash(services: object, run_id: UUID) -> str | None:
    with services.make_uow() as uow:  # type: ignore[attr-defined]
        arts = uow.artifacts.list_for_run(run_id)
    for art in arts:
        if getattr(art, "kind", None) == "trace":
            return str(art.sha256)
    return None


@app.callback(invoke_without_command=True)
def replay_cmd(  # noqa: PLR0912, PLR0913, PLR0917 - Typer option surface
    ctx: typer.Context,
    run_id: Annotated[str, typer.Argument(help="Source run UUID.")],
    repeats: Annotated[int, typer.Option("--repeats", min=1)] = 1,
    fresh_seeds: Annotated[bool, typer.Option("--fresh-seeds")] = False,
    fail_on_disagreement: Annotated[bool, typer.Option("--fail-on-disagreement")] = False,
    inline: Annotated[bool, typer.Option("--inline", help="Execute replays in-process.")] = True,
) -> None:
    """Enqueue replay runs and print an agreement summary."""
    if ctx.invoked_subcommand is not None:
        return
    state = get_state(ctx)
    settings = state.bootstrap()
    services = build_cli_services(settings)
    rid = _parse_id(run_id)
    try:
        ids = enqueue_replays(
            services.uow_factory,
            ReplayRequest(run_id=rid, repeats=repeats, fresh_seeds=fresh_seeds),
        )
        if inline:
            with services.make_uow() as uow:
                source = uow.runs.get(rid)
                if source is None:
                    msg = "run not found"
                    raise NotFoundError(msg, context={"run_id": run_id})
                campaign = uow.campaigns.get(source.campaign_id)
                if campaign is None:
                    msg = "campaign missing"
                    raise NotFoundError(msg)
            space = ScenarioSpace.from_yaml(
                REPO_ROOT / "configs" / "scenario_spaces" / f"{campaign.space_id}.yaml",
                base_dir=REPO_ROOT,
            )
            worker_settings = settings.model_copy(
                update={
                    "worker": settings.worker.model_copy(
                        update={
                            "backend": campaign.backend,
                            "poll_interval_s": min(settings.worker.poll_interval_s, 0.05),
                        }
                    )
                }
            )
            worker = build_worker(worker_settings, task=space.task, infra=services.infra)
            # Drain the replay batch.
            pending = set(ids)
            deadline = time.monotonic() + settings.worker.drain_timeout_s
            while pending and time.monotonic() < deadline:
                claimed = worker.claim()
                if claimed is None:
                    time.sleep(worker_settings.worker.poll_interval_s)
                    continue
                worker.execute(claimed)
                pending.discard(claimed.run_id)
                with services.make_uow() as uow:
                    for item in list(pending):
                        row = uow.runs.get(item)
                        if row is not None and RunStatus(
                            str(getattr(row.status, "value", row.status))
                        ) in {
                            RunStatus.DONE,
                            RunStatus.ERROR,
                            RunStatus.CANCELLED,
                        }:
                            pending.discard(item)
        hashes: dict[UUID, str] = {}
        source_hash = _trace_hash(services, rid)
        if source_hash is not None:
            hashes[rid] = source_hash
        for item in ids:
            h = _trace_hash(services, item)
            if h is not None:
                hashes[item] = h
        summary = summarise_agreement(
            services.uow_factory,
            rid,
            ids,
            trace_hashes=hashes or None,
        )
        state.output.data(
            {
                "source_run_id": str(rid),
                "replay_ids": [str(i) for i in ids],
                "source_verdict": summary.source_verdict,
                "agreements": summary.agreements,
                "disagreements": summary.disagreements,
                "trace_matches": summary.trace_matches,
                "rows": list(summary.rows),
            }
        )
        if fail_on_disagreement and not summary.all_agree:
            raise typer.Exit(3)
    finally:
        services.close()
