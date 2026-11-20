"""``roboprobe experiment run|report`` (docs/05 §11, docs/14 §8).

Layer: Interface (L4).

Implements: T-102b, FR-EXP-001, FR-EXP-002, FR-CLI-001
"""

from __future__ import annotations

import importlib
from pathlib import Path
from types import ModuleType
from typing import Annotated, cast
from uuid import UUID, uuid4

import typer

from roboprobe import __version__ as package_version
from roboprobe.bootstrap import build_cli_services
from roboprobe.cli._context import get_state
from roboprobe.cli.campaign import run_inline
from roboprobe.cli.space import REPO_ROOT, register_space
from roboprobe.core.clock import SystemClock
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.types import CampaignStatus, JsonValue, Verdict
from roboprobe.experiments.planner import CampaignSpec, ComparabilityKey, load_design
from roboprobe.experiments.runner import ExperimentRunner
from roboprobe.metrics.campaign_metrics import CampaignRun
from roboprobe.oracles import __version__ as oracle_set_version
from roboprobe.reporting.ports import ReportArtifactStore, ReportUnitOfWork
from roboprobe.runner.ports import UowFactory
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.sut_profile import load_sut_profile

__all__ = ["app"]

app = typer.Typer(name="experiment", help="Strategy comparison experiments.", no_args_is_help=True)

_SUT_DIR = REPO_ROOT / "configs" / "sut_profiles"


def _records() -> ModuleType:
    return importlib.import_module("roboprobe.store.records")


class _UowWriter:
    """ExperimentWriter backed by a live UnitOfWork factory."""

    def __init__(self, make_uow: UowFactory, clock: SystemClock) -> None:
        self._make_uow = make_uow
        self._clock = clock

    def add_experiment(self, *, name: str, design: dict[str, JsonValue], status: str) -> UUID:
        eid = uuid4()
        with self._make_uow() as uow:
            uow.experiments.add(
                _records().ExperimentRecord(id=eid, name=name, design=design, status=status)
            )
            uow.commit()
        return eid

    def add_campaign(self, spec: CampaignSpec, experiment_id: UUID) -> UUID:
        cid = uuid4()
        sut = spec.sut_profile_id or "k2d_default"
        with self._make_uow() as uow:
            uow.campaigns.add(
                _records().CampaignRecord(
                    id=cid,
                    name=spec.name,
                    space_id=spec.space_id,
                    space_version=spec.space_version,
                    sut_profile_id=sut,
                    backend=spec.backend,
                    strategy_id=spec.strategy_id,
                    strategy_params=dict(spec.strategy_params),
                    seed=spec.seed,
                    budget=spec.budget,
                    repeats=spec.repeats,
                    batch_size=spec.batch_size,
                    pins=dict(spec.pins),
                    oracle_config=dict(spec.oracle_overrides),
                    stop_rules=dict(spec.stop_rules),
                    status=CampaignStatus.CREATED,
                    experiment_id=experiment_id,
                    experiment_rep=spec.experiment_rep,
                    tags=spec.tags,
                )
            )
            uow.commit()
        return cid

    def get_experiment(self, experiment_id: UUID) -> object | None:
        with self._make_uow() as uow:
            found: object | None = uow.experiments.get(experiment_id)
            return found

    def set_experiment_status(
        self, experiment_id: UUID, status: str, *, finished: bool = False
    ) -> None:
        del finished  # finished_at stamped by DB triggers / future set_finished helper
        with self._make_uow() as uow:
            uow.experiments.set_status(experiment_id, status)
            uow.commit()

    def set_experiment_results(self, experiment_id: UUID, results: dict[str, JsonValue]) -> None:
        with self._make_uow() as uow:
            uow.experiments.set_results(experiment_id, results)
            uow.commit()

    def list_campaigns(self, experiment_id: UUID) -> list[object]:
        with self._make_uow() as uow:
            return list(uow.campaigns.list_for_experiment(experiment_id))

    def campaign_runs(self, campaign_id: UUID) -> list[CampaignRun]:
        with self._make_uow() as uow:
            page = uow.runs.list_for_campaign(campaign_id, limit=None)
            rows = sorted(page.items, key=lambda r: (r.ordinal, r.repeat_index))
        out: list[CampaignRun] = []
        for row in rows:
            if row.verdict is None:
                continue
            verdict = row.verdict if isinstance(row.verdict, Verdict) else Verdict(str(row.verdict))
            duration = (row.metrics or {}).get("duration_s", 0.0)
            out.append(
                CampaignRun(
                    verdict=verdict,
                    wall_time_s=float(cast(float | int | str, duration)),
                    x_unit=tuple(float(x) for x in row.x_unit),
                    phase=str(row.phase or ""),
                    tags=tuple(str(t) for t in row.tags),
                )
            )
        return out


def _resolve_key(space: ScenarioSpace, sut_hash: str, backend: str) -> ComparabilityKey:
    k2d = "kinematic2d" if backend == "kinematic2d" else "n/a"
    return ComparabilityKey(
        space_version=space.version,
        oracle_set_version=oracle_set_version,
        sut_config_hash=sut_hash,
        backend_version=package_version,
        k2d_model_version=k2d,
    )


@app.command("run")
def experiment_run(
    ctx: typer.Context,
    yaml_path: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    resume: Annotated[
        UUID | None, typer.Option("--resume", help="Resume an existing experiment id.")
    ] = None,
    workers: Annotated[int, typer.Option("--workers", min=1)] = 1,
    raw_out: Annotated[
        Path | None, typer.Option("--raw-parquet", help="Write raw run Parquet here.")
    ] = None,
) -> None:
    """Plan and run campaigns for ``yaml_path`` (inline concurrency-limited)."""
    state = get_state(ctx)
    settings = state.bootstrap()
    design = load_design(yaml_path)
    space_yaml = REPO_ROOT / "configs" / "scenario_spaces" / f"{design.space.id}.yaml"
    if not space_yaml.is_file():
        msg = f"scenario space not found: {space_yaml}"
        raise NotFoundError(msg, context={"space_id": design.space.id})
    register_space(space_yaml, settings, base_dir=REPO_ROOT)
    space = ScenarioSpace.from_yaml(space_yaml, base_dir=REPO_ROOT)
    sut_id = design.sut_profile_id or "k2d_default"
    sut_path = _SUT_DIR / f"{sut_id}.yaml"
    if not sut_path.is_file():
        msg = f"SUT profile not found: {sut_path}"
        raise NotFoundError(msg, context={"sut_profile_id": sut_id})
    profile = load_sut_profile(sut_path, strict=False)
    key = _resolve_key(space, profile.config_hash, design.backend)
    services = build_cli_services(settings)
    clock = SystemClock()
    writer = _UowWriter(cast(UowFactory, services.make_uow), clock)

    def drive(campaign_id: UUID) -> CampaignStatus:
        services.campaigns.start(campaign_id)
        return run_inline(campaign_id, settings, workers=workers)

    runner = ExperimentRunner(
        writer,
        settings.experiments,
        clock,
        drive,
        new_uuid=uuid4,
    )
    try:
        eid, comparison = runner.start(design, key, experiment_id=resume, raw_parquet=raw_out)
    finally:
        services.close()
    state.output.data({"experiment_id": str(eid), "comparison": comparison})


@app.command("report")
def experiment_report(
    ctx: typer.Context,
    experiment_id: Annotated[UUID, typer.Argument()],
    as_table: Annotated[bool, typer.Option("--table", help="Print a summary table.")] = False,
    html_out: Annotated[
        Path | None, typer.Option("-o", "--output", help="Write offline HTML report.")
    ] = None,
) -> None:
    """Print stored experiment comparison JSON, a table, or HTML report."""
    state = get_state(ctx)
    settings = state.bootstrap()
    services = build_cli_services(settings)
    clock = SystemClock()
    if html_out is not None:
        render = importlib.import_module("roboprobe.reporting.experiment").render_experiment_report
        uow = cast(ReportUnitOfWork, services.make_uow())
        store = cast(ReportArtifactStore, services.infra.artifact_store)
        try:
            with uow:
                path = render(
                    experiment_id,
                    uow,
                    store,
                    out=html_out,
                    settings=settings.reporting,
                    experiment_settings=settings.experiments,
                )
        finally:
            services.close()
        state.output.data({"path": str(path)})
        return
    writer = _UowWriter(cast(UowFactory, services.make_uow), clock)
    runner = ExperimentRunner(
        writer,
        settings.experiments,
        clock,
        drive=lambda _cid: CampaignStatus.COMPLETED,
        new_uuid=uuid4,
    )
    try:
        payload = runner.report(experiment_id)
    finally:
        services.close()
    if as_table:
        strategies = payload.get("strategies", {})
        if not isinstance(strategies, dict):
            msg = "comparison.strategies must be a mapping"
            raise ValidationError(msg)
        rows = [[name, str(block)] for name, block in strategies.items()]
        state.output.table(["strategy", "metrics"], rows, title=f"experiment {experiment_id}")
        return
    state.output.data(payload)
