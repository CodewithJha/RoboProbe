"""``roboprobe run --scenario`` — ad-hoc single-run campaigns.

Layer: Interface (L4).

Implements: T-045c, FR-SCN-008, FR-CLI-001
"""

from __future__ import annotations

import importlib
import time
from pathlib import Path
from typing import Annotated

import typer
import yaml

from roboprobe.bootstrap import build_cli_services, build_worker
from roboprobe.cli._context import get_state
from roboprobe.cli.campaign import create_campaign_from_config
from roboprobe.cli.space import REPO_ROOT
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.seeding import RUN, derive_seed
from roboprobe.core.types import RunStatus, Verdict
from roboprobe.scenario.regression import load_regression
from roboprobe.scenario.space import ScenarioSpace

__all__ = ["app"]

app = typer.Typer(
    name="run",
    help="Ad-hoc single scenario execution.",
    invoke_without_command=True,
)


@app.callback(invoke_without_command=True)
def run_cmd(  # noqa: PLR0915 - Typer option surface + ad-hoc wiring
    ctx: typer.Context,
    scenario: Annotated[
        Path | None,
        typer.Option("--scenario", exists=True, dir_okay=False, help="Regression YAML."),
    ] = None,
    backend: Annotated[str, typer.Option("--backend")] = "kinematic2d",
    seed: Annotated[int | None, typer.Option("--seed")] = None,
    fail_on_failure: Annotated[bool, typer.Option("--fail-on-failure")] = False,
) -> None:
    """Execute one regression scenario as a one-off manual campaign."""
    if ctx.invoked_subcommand is not None:
        return
    if scenario is None:
        msg = "--scenario is required"
        raise ValidationError(msg)
    state = get_state(ctx)
    settings = state.bootstrap()
    space_hint = _space_id(scenario)
    space = ScenarioSpace.from_yaml(
        REPO_ROOT / "configs" / "scenario_spaces" / f"{space_hint}.yaml",
        base_dir=REPO_ROOT,
    )
    regression = load_regression(scenario, space=space)
    run_seed = seed if seed is not None else regression.seed
    if run_seed is None:
        msg = "scenario has no seed; pass --seed"
        raise ValidationError(msg)
    tmp = Path(settings.storage.workdir_root) / f"adhoc-{run_seed}.yaml"
    tmp.parent.mkdir(parents=True, exist_ok=True)
    doc = {
        "schema_version": 1,
        "name": f"adhoc-{regression.scenario.scenario_hash[:8]}",
        "space": {
            "id": regression.scenario.space_id,
            "version": regression.scenario.space_version,
        },
        "sut_profile_id": "k2d_default",
        "backend": backend,
        "strategy": {"id": "S-RANDOM", "seed": run_seed},
        "budget": 1,
        "batch_size": 1,
        "repeats": 1,
        "start": True,
    }
    tmp.write_text(yaml.safe_dump(doc), encoding="utf-8")
    settings = settings.model_copy(
        update={
            "worker": settings.worker.model_copy(
                update={
                    "backend": backend,
                    "poll_interval_s": min(settings.worker.poll_interval_s, 0.05),
                }
            ),
            "observability": settings.observability.model_copy(update={"metrics_enabled": False}),
        }
    )
    cid = create_campaign_from_config(tmp, settings, seed_override=run_seed)
    values = dict(regression.scenario.values)
    x_unit = tuple(float(x) for x in space.to_unit(values))
    records = importlib.import_module("roboprobe.store.records")
    services = build_cli_services(settings)
    try:
        with services.make_uow() as uow:
            (run_id,) = uow.runs.insert_batch(
                [
                    records.NewRun(
                        campaign_id=cid,
                        ordinal=0,
                        backend=backend,
                        scenario_hash=regression.scenario.scenario_hash,
                        scenario_values=values,
                        x_unit=x_unit,
                        seed=derive_seed(run_seed, RUN, 0, 0),
                        phase="manual",
                        tags=("manual",),
                    )
                ]
            )
            uow.commit()
        worker = build_worker(settings, task=space.task, infra=services.infra)
        deadline = time.monotonic() + settings.worker.drain_timeout_s
        while time.monotonic() < deadline:
            with services.make_uow() as uow:
                row = uow.runs.get(run_id)
            if row is not None and RunStatus(str(getattr(row.status, "value", row.status))) in {
                RunStatus.DONE,
                RunStatus.ERROR,
                RunStatus.CANCELLED,
            }:
                break
            claimed = worker.claim()
            if claimed is None:
                time.sleep(settings.worker.poll_interval_s)
                continue
            worker.execute(claimed)
        with services.make_uow() as uow:
            run = uow.runs.get(run_id)
            if run is None:
                msg = "ad-hoc run missing after execution"
                raise NotFoundError(msg, context={"run_id": str(run_id)})
        verdict = _verdict(run.verdict)
        state.output.data(
            {
                "campaign_id": str(cid),
                "run_id": str(run_id),
                "verdict": None if verdict is None else verdict.value,
                "expect": None if regression.expect is None else regression.expect.verdict.value,
            }
        )
        if fail_on_failure and (
            (regression.expect is not None and verdict is not regression.expect.verdict)
            or verdict is Verdict.FAIL
        ):
            raise typer.Exit(3)
    finally:
        services.close()


def _space_id(path: Path) -> str:
    raw = yaml.safe_load(path.read_text(encoding="utf-8"))
    if not isinstance(raw, dict):
        msg = "scenario file must be a mapping"
        raise ValidationError(msg, context={"path": str(path)})
    space = raw.get("space")
    if isinstance(space, dict) and "id" in space:
        return str(space["id"])
    msg = "scenario.space.id is required"
    raise ValidationError(msg, context={"path": str(path)})


def _verdict(value: object) -> Verdict | None:
    if value is None:
        return None
    if isinstance(value, Verdict):
        return value
    return Verdict(str(getattr(value, "value", value)))
