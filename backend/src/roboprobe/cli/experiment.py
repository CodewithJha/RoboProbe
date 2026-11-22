"""``roboprobe experiment run|report`` (docs/05 §11, docs/14 §8).

Layer: Interface (L4).

Implements: T-102b, FR-EXP-001, FR-EXP-002, FR-CLI-001
"""

from __future__ import annotations

import importlib
from pathlib import Path
from typing import Annotated, cast
from uuid import UUID, uuid4

import typer

from roboprobe import __version__ as package_version
from roboprobe.bootstrap import build_cli_services
from roboprobe.bootstrap.experiments import SqlExperimentWriter
from roboprobe.cli._context import get_state
from roboprobe.cli.campaign import run_inline
from roboprobe.cli.space import REPO_ROOT, register_space
from roboprobe.core.clock import SystemClock
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.types import CampaignStatus
from roboprobe.experiments.planner import ComparabilityKey, load_design
from roboprobe.experiments.runner import ExperimentRunner
from roboprobe.oracles import __version__ as oracle_set_version
from roboprobe.reporting.ports import ReportArtifactStore, ReportUnitOfWork
from roboprobe.runner.catalog import SutProfileService
from roboprobe.scenario._documents import read_document
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.sut_profile import load_sut_profile_text

__all__ = ["app"]

app = typer.Typer(name="experiment", help="Strategy comparison experiments.", no_args_is_help=True)

_SUT_DIR = REPO_ROOT / "configs" / "sut_profiles"


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
    profile_source = str(sut_path)
    profile_document = read_document(sut_path)
    profile = load_sut_profile_text(profile_document, source=profile_source)
    if profile.id != sut_id:
        msg = f"SUT profile id {profile.id!r} does not match file name {sut_id!r}"
        raise ValidationError(msg, context={"sut_profile_id": sut_id})
    key = _resolve_key(space, profile.config_hash, design.backend)
    services = build_cli_services(settings)
    clock = SystemClock()
    writer = SqlExperimentWriter(services.make_uow)

    def drive(campaign_id: UUID) -> CampaignStatus:
        services.campaigns.start(campaign_id)
        worker_settings = settings.worker.model_copy(
            update={"id_prefix": f"{settings.worker.id_prefix}:{campaign_id.hex}"}
        )
        campaign_settings = settings.model_copy(update={"worker": worker_settings})
        return run_inline(campaign_id, campaign_settings, workers=workers, serve_probe=False)

    runner = ExperimentRunner(
        writer,
        settings.experiments,
        clock,
        drive,
        new_uuid=uuid4,
    )
    try:
        profiles = SutProfileService(services.uow_factory)
        profiles.create_bytes(profile_document, source=profile_source)
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
    writer = SqlExperimentWriter(services.make_uow)
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
