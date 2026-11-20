"""``roboprobe oracle reevaluate`` — offline re-judgement from stored traces.

Layer: Interface (L4).

Implements: T-039b, FR-ORC-006
"""

from __future__ import annotations

import tomllib
from pathlib import Path
from typing import Annotated
from uuid import UUID

import typer

from roboprobe.bootstrap import build_cli_services
from roboprobe.cli._context import get_state
from roboprobe.cli.space import REPO_ROOT
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.settings import OracleThresholds, RoboProbeSettings
from roboprobe.oracles.reevaluate import reevaluate_run
from roboprobe.scenario.space import ScenarioSpace

__all__ = ["app"]

app = typer.Typer(name="oracle", help="Oracle helpers.", no_args_is_help=True)


def _parse_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        msg = f"invalid run id: {value}"
        raise ValidationError(msg, context={"run_id": value}) from exc


def _load_thresholds(path: Path | None, settings: RoboProbeSettings) -> OracleThresholds:
    if path is None:
        return settings.oracles
    raw = tomllib.loads(path.read_text(encoding="utf-8"))
    section = raw.get("oracles", raw)
    if not isinstance(section, dict):
        msg = "thresholds file must contain an [oracles] table or oracle mapping"
        raise ValidationError(msg, context={"path": str(path)})
    return OracleThresholds.model_validate(section)


@app.command("reevaluate")
def reevaluate_cmd(
    ctx: typer.Context,
    run_id: Annotated[str, typer.Argument()],
    thresholds: Annotated[
        Path | None,
        typer.Option("--thresholds", exists=True, dir_okay=False, help="TOML overrides."),
    ] = None,
    write: Annotated[bool, typer.Option("--write", help="Persist recomputed results.")] = False,
) -> None:
    """Re-judge a run from its stored trace and report differences."""
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
            arts = uow.artifacts.list_for_run(rid)
        trace_art = next((a for a in arts if a.kind == "trace"), None)
        if trace_art is None:
            msg = "run has no trace artefact"
            raise NotFoundError(msg, context={"run_id": run_id})
        trace_path = Path(settings.storage.artifact_root) / trace_art.rel_path
        space = ScenarioSpace.from_yaml(
            REPO_ROOT / "configs" / "scenario_spaces" / f"{campaign.space_id}.yaml",
            base_dir=REPO_ROOT,
        )
        diff = reevaluate_run(
            services.uow_factory,
            rid,
            task=space.task,
            artifact_path=trace_path,
            thresholds=_load_thresholds(thresholds, settings),
            write=write,
        )
        state.output.data(
            {
                "run_id": run_id,
                "stored_verdict": diff.stored_verdict,
                "stored_robustness": diff.stored_robustness,
                "new_verdict": diff.new_outcome.verdict.value,
                "new_robustness": diff.new_outcome.robustness,
                "changed": diff.changed,
                "written": write,
                "oracle_set_version": diff.oracle_set_version,
            }
        )
    finally:
        services.close()
