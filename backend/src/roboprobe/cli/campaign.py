"""``roboprobe campaign``: create, lifecycle, status and inline ``run``.

Layer: Interface (L4).

Implements: T-045b, FR-CLI-001, PR-02
"""

from __future__ import annotations

import importlib
import tempfile
import threading
import time
from pathlib import Path
from types import ModuleType
from typing import Annotated, cast
from uuid import UUID

import numpy as np
import typer
import yaml

from roboprobe.bootstrap import build_cli_services, build_orchestrator, build_worker
from roboprobe.bootstrap.cli import CliServices
from roboprobe.cli._context import get_state
from roboprobe.cli.space import REPO_ROOT, register_space
from roboprobe.core.clock import SystemClock
from roboprobe.core.errors import NotFoundError, ValidationError
from roboprobe.core.seeding import random_campaign_seed
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import CampaignStatus, JsonValue, RunStatus, Verdict
from roboprobe.runner.heartbeat import HeartbeatService
from roboprobe.runner.lifecycle import CampaignService
from roboprobe.runner.loop import CampaignLoop
from roboprobe.runner.scheduler import Scheduler
from roboprobe.runner.stop_rules import counters_from_runs, evaluate_stop_rules
from roboprobe.scenario._documents import load_yaml_document, read_document, validate_document
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.scenario.sut_profile import load_sut_profile
from roboprobe.selection.base import StrategyContext
from roboprobe.selection.registry import create as create_strategy

__all__ = ["app", "create_campaign_from_config", "run_inline"]

app = typer.Typer(name="campaign", help="Campaign create / lifecycle / run.", no_args_is_help=True)

_SUT_DIR = REPO_ROOT / "configs" / "sut_profiles"
_TERMINAL = frozenset({CampaignStatus.COMPLETED, CampaignStatus.FAILED, CampaignStatus.CANCELLED})


def _records() -> ModuleType:
    return importlib.import_module("roboprobe.store.records")


def _ids() -> ModuleType:
    return importlib.import_module("roboprobe.store.ids")


def _load_campaign_doc(path: Path) -> dict[str, JsonValue]:
    document = load_yaml_document(read_document(path), source=str(path))
    validate_document(document, schema="campaign", source=str(path))
    if not isinstance(document, dict):
        msg = "campaign document must be a mapping"
        raise ValidationError(msg, context={"path": str(path)})
    return {str(key): value for key, value in document.items()}


def _ensure_sut(services: CliServices, profile_id: str, backend: str) -> str:
    path = _SUT_DIR / f"{profile_id}.yaml"
    if not path.is_file():
        msg = f"SUT profile file not found: {path}"
        raise NotFoundError(msg, context={"sut_profile_id": profile_id})
    profile = load_sut_profile(path, strict=False)
    if profile.backend != backend:
        msg = (
            f"SUT profile {profile_id!r} backend {profile.backend!r} "
            f"!= campaign backend {backend!r}"
        )
        raise ValidationError(msg, context={"sut_profile_id": profile_id})
    with services.make_uow() as uow:
        if uow.sut_profiles.get(profile.id) is None:
            uow.sut_profiles.add(
                _records().SutProfileRecord(
                    id=profile.id,
                    backend=profile.backend,
                    config=dict(profile.config),
                    config_hash=profile.config_hash,
                )
            )
        uow.commit()
    return profile.id


def _resolve_seed(strategy: dict[str, JsonValue], seed_override: int | None) -> int:
    if seed_override is not None:
        return seed_override
    raw = strategy.get("seed")
    if raw is None:
        return random_campaign_seed(np.random.default_rng())
    return int(raw)  # type: ignore[arg-type]


def _as_mapping(value: JsonValue | None) -> dict[str, JsonValue]:
    if value is None:
        return {}
    if isinstance(value, dict):
        return dict(value)
    return {}


def _as_str_tuple(value: JsonValue | None) -> tuple[str, ...]:
    if value is None:
        return ()
    if isinstance(value, list):
        return tuple(str(item) for item in value)
    return ()


def create_campaign_from_config(
    path: Path,
    settings: RoboProbeSettings,
    *,
    seed_override: int | None = None,
) -> UUID:
    """Validate ``path``, ensure space/SUT rows, insert a campaign; return its id."""
    doc = _load_campaign_doc(path)
    space_ref = doc["space"]
    if not isinstance(space_ref, dict):
        msg = "campaign.space must be an object"
        raise ValidationError(msg)
    space_id = str(space_ref["id"])
    backend = str(doc["backend"])
    strategy = doc["strategy"]
    if not isinstance(strategy, dict):
        msg = "campaign.strategy must be an object"
        raise ValidationError(msg)
    budget = int(doc["budget"])  # type: ignore[arg-type]
    if budget > settings.runner.max_budget:
        msg = f"budget {budget} exceeds runner.max_budget {settings.runner.max_budget}"
        raise ValidationError(msg, context={"budget": budget})
    batch_size = int(doc.get("batch_size", 1))  # type: ignore[arg-type]
    if batch_size > settings.runner.max_batch_size:
        msg = f"batch_size {batch_size} exceeds runner.max_batch_size"
        raise ValidationError(msg, context={"batch_size": batch_size})
    space_yaml = REPO_ROOT / "configs" / "scenario_spaces" / f"{space_id}.yaml"
    register_space(space_yaml, settings, base_dir=REPO_ROOT)
    space = ScenarioSpace.from_yaml(space_yaml, base_dir=REPO_ROOT)
    if "version" in space_ref and str(space_ref["version"]) != space.version:
        msg = "campaign.space.version does not match registered space"
        raise ValidationError(msg, context={"expected": space.version})
    default_sut = "k2d_default" if backend == "kinematic2d" else ""
    profile_id = str(doc.get("sut_profile_id") or default_sut)
    if not profile_id:
        msg = "sut_profile_id is required"
        raise ValidationError(msg)
    services = build_cli_services(settings)
    try:
        _ensure_sut(services, profile_id, backend)
        seed = _resolve_seed(strategy, seed_override)
        cid = _ids().new_uuid()
        name = str(doc.get("name") or f"{space_id}-{strategy['id']}")
        with services.make_uow() as uow:
            uow.campaigns.add(
                _records().CampaignRecord(
                    id=cid,
                    name=name,
                    space_id=space.id,
                    space_version=space.version,
                    sut_profile_id=profile_id,
                    backend=backend,
                    strategy_id=str(strategy["id"]),
                    strategy_params=_as_mapping(strategy.get("params")),
                    seed=seed,
                    budget=budget,
                    repeats=int(doc.get("repeats", 1)),  # type: ignore[arg-type]
                    batch_size=batch_size,
                    pins=_as_mapping(doc.get("pins")),
                    oracle_config=_as_mapping(doc.get("oracle_overrides")),
                    stop_rules=_as_mapping(doc.get("stop_rules")),
                    status=CampaignStatus.CREATED,
                    tags=_as_str_tuple(doc.get("tags")),
                )
            )
            uow.commit()
        if doc.get("start"):
            services.campaigns.start(cid)
        return cast("UUID", cid)
    finally:
        services.close()


def _list_runs(uow: object, campaign_id: UUID) -> list[object]:
    runs: list[object] = []
    cursor: str | None = None
    while True:
        page = uow.runs.list_for_campaign(campaign_id, limit=None, cursor=cursor)  # type: ignore[attr-defined]
        runs.extend(page.items)
        cursor = page.next_cursor
        if cursor is None:
            break
    return runs


def _status_value(value: object) -> str:
    return value.value if isinstance(value, RunStatus | Verdict | CampaignStatus) else str(value)


def run_inline(  # noqa: PLR0912,PLR0915 - inline supervisor wires loop, workers and stop rules
    campaign_id: UUID,
    settings: RoboProbeSettings,
    *,
    workers: int,
) -> CampaignStatus:
    """Drive one campaign in-process: CampaignLoop + ``workers`` worker threads."""
    orch = build_orchestrator(settings)
    cli = build_cli_services(settings)
    stop = threading.Event()
    heartbeats: list[HeartbeatService] = []
    try:
        with cli.make_uow() as uow:
            campaign = uow.campaigns.get(campaign_id)
            if campaign is None:
                msg = "campaign not found"
                raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
        space_yaml = REPO_ROOT / "configs" / "scenario_spaces" / f"{campaign.space_id}.yaml"
        space = ScenarioSpace.from_yaml(space_yaml, base_dir=REPO_ROOT)
        ctx = StrategyContext(
            space=space,
            budget=campaign.budget,
            seed=campaign.seed,
            batch_size=campaign.batch_size,
            params=dict(campaign.strategy_params),
        )
        strategy = create_strategy(campaign.strategy_id, ctx)
        loop = CampaignLoop(
            campaign_id,
            uow_factory=orch.uow_factory,
            settings=settings.runner,
            selection=settings.selection,
            space=space,
            strategy=strategy,
            scheduler=Scheduler(settings.runner),
            clock=SystemClock(),
            metrics=orch.metrics,
        )
        worker_settings = settings.model_copy(
            update={
                "worker": settings.worker.model_copy(update={"backend": campaign.backend}),
            }
        )
        threads: list[threading.Thread] = []
        for slot in range(workers):
            slot_settings = worker_settings.model_copy(
                update={
                    "worker": worker_settings.worker.model_copy(
                        update={"health_port": worker_settings.worker.health_port + slot}
                    )
                }
            )
            worker = build_worker(slot_settings, task=space.task, slot=slot, infra=orch.infra)
            hb = HeartbeatService(
                worker=worker,
                uow_factory=orch.uow_factory,
                clock=SystemClock(),
                settings=slot_settings.worker,
                retry=settings.runner.retry,
                heartbeat_timeout_s=settings.runner.heartbeat_timeout_s,
                metrics=orch.metrics,
            )
            hb.register()
            hb.start()
            heartbeats.append(hb)
            threads.append(
                threading.Thread(
                    target=worker.serve_forever,
                    args=(stop,),
                    name=f"worker-{slot}",
                    daemon=True,
                )
            )
        for thread in threads:
            thread.start()
        campaigns = CampaignService(orch.uow_factory)
        if campaign.status is CampaignStatus.CREATED:
            campaigns.start(campaign_id)
        clock = SystemClock()
        while not stop.is_set():
            with cli.make_uow() as uow:
                current = uow.campaigns.get(campaign_id)
                if current is None:
                    break
                if current.status in _TERMINAL or current.status is CampaignStatus.PAUSED:
                    break
                if current.status is not CampaignStatus.RUNNING:
                    time.sleep(settings.runner.tick_interval_s)
                    continue
                runs = _list_runs(uow, campaign_id)
                counters = counters_from_runs(
                    budget=current.budget,
                    runs=runs,  # type: ignore[arg-type]
                    modes_found=0,
                    started_at=current.started_at,
                    now=clock.now(),
                    stop_rules=dict(current.stop_rules),
                )
                decision = evaluate_stop_rules(counters, settings.runner)
            if decision.action == "analyze":
                campaigns.mark_analyzing(campaign_id, reason=decision.reason)
                campaigns.complete(campaign_id, reason=decision.reason)
                break
            if decision.action == "pause":
                campaigns.pause(campaign_id, reason=decision.reason)
                break
            if threads and all(not thread.is_alive() for thread in threads):
                campaigns.fail(campaign_id, reason="all_workers_dead")
                break
            loop.step()
            orch.reaper.reap()
            time.sleep(settings.runner.tick_interval_s)
        stop.set()
        for thread in threads:
            thread.join(timeout=settings.worker.drain_timeout_s)
        with cli.make_uow() as uow:
            final = uow.campaigns.get(campaign_id)
            return final.status if final is not None else CampaignStatus.FAILED
    finally:
        stop.set()
        for hb in heartbeats:
            hb.stop()
        cli.close()
        orch.close()


def _parse_id(value: str) -> UUID:
    try:
        return UUID(value)
    except ValueError as exc:
        msg = f"invalid campaign id: {value}"
        raise ValidationError(msg, context={"campaign_id": value}) from exc


def _lifecycle(ctx: typer.Context, campaign_id: str, action: str) -> None:
    state = get_state(ctx)
    settings = state.bootstrap()
    services = build_cli_services(settings)
    try:
        svc = services.campaigns
        cid = _parse_id(campaign_id)
        status = {
            "start": svc.start,
            "pause": svc.pause,
            "resume": svc.resume,
            "cancel": svc.cancel,
        }[action](cid)
        state.output.data({"campaign_id": campaign_id, "status": status.value})
    finally:
        services.close()


@app.command("create")
def create_cmd(  # noqa: PLR0913, PLR0917 - Typer option surface matches docs/05 §11
    ctx: typer.Context,
    config: Annotated[
        Path | None,
        typer.Option("--config", exists=True, dir_okay=False, help="Campaign YAML."),
    ] = None,
    space: Annotated[str | None, typer.Option("--space")] = None,
    backend: Annotated[str, typer.Option("--backend")] = "kinematic2d",
    strategy: Annotated[str, typer.Option("--strategy")] = "S-RANDOM",
    budget: Annotated[int, typer.Option("--budget")] = 100,
    seed: Annotated[int | None, typer.Option("--seed")] = None,
    repeats: Annotated[int, typer.Option("--repeats")] = 1,
    batch: Annotated[int, typer.Option("--batch")] = 4,
) -> None:
    """Create a campaign from flags or a YAML config file."""
    state = get_state(ctx)
    settings = state.bootstrap()
    if config is not None:
        cid = create_campaign_from_config(config, settings, seed_override=seed)
        state.output.data({"campaign_id": str(cid)})
        return
    if not space:
        msg = "either --config or --space is required"
        raise ValidationError(msg)
    payload = {
        "schema_version": 1,
        "space": {"id": space},
        "backend": backend,
        "strategy": {"id": strategy, **({"seed": seed} if seed is not None else {})},
        "budget": budget,
        "repeats": repeats,
        "batch_size": batch,
        "sut_profile_id": "k2d_default" if backend == "kinematic2d" else "tb4_nav2_default",
    }
    with tempfile.NamedTemporaryFile("w", suffix=".yaml", delete=False) as handle:
        yaml.safe_dump(payload, handle)
        tmp_path = Path(handle.name)
    try:
        cid = create_campaign_from_config(tmp_path, settings, seed_override=seed)
    finally:
        tmp_path.unlink(missing_ok=True)
    state.output.data({"campaign_id": str(cid)})


@app.command("start")
def start_cmd(ctx: typer.Context, campaign_id: Annotated[str, typer.Argument()]) -> None:
    """Start a CREATED/PAUSED campaign."""
    _lifecycle(ctx, campaign_id, "start")


@app.command("pause")
def pause_cmd(ctx: typer.Context, campaign_id: Annotated[str, typer.Argument()]) -> None:
    """Pause a RUNNING campaign."""
    _lifecycle(ctx, campaign_id, "pause")


@app.command("resume")
def resume_cmd(ctx: typer.Context, campaign_id: Annotated[str, typer.Argument()]) -> None:
    """Resume a PAUSED campaign."""
    _lifecycle(ctx, campaign_id, "resume")


@app.command("cancel")
def cancel_cmd(ctx: typer.Context, campaign_id: Annotated[str, typer.Argument()]) -> None:
    """Cancel a campaign."""
    _lifecycle(ctx, campaign_id, "cancel")


@app.command("status")
def status_cmd(
    ctx: typer.Context,
    campaign_id: Annotated[str, typer.Argument()],
    watch: Annotated[bool, typer.Option("--watch")] = False,
) -> None:
    """Show campaign progress (optional live refresh)."""
    state = get_state(ctx)
    settings = state.bootstrap()
    services = build_cli_services(settings)
    cid = _parse_id(campaign_id)
    try:
        while True:
            with services.make_uow() as uow:
                campaign = uow.campaigns.get(cid)
                if campaign is None:
                    msg = "campaign not found"
                    raise NotFoundError(msg, context={"campaign_id": campaign_id})
                runs = _list_runs(uow, cid)
            done = sum(1 for r in runs if _status_value(getattr(r, "status", "")) == "DONE")
            fail = sum(1 for r in runs if _status_value(getattr(r, "verdict", "")) == "FAIL")
            state.output.data(
                {
                    "campaign_id": campaign_id,
                    "status": campaign.status.value,
                    "budget": campaign.budget,
                    "done": done,
                    "fail": fail,
                    "total_runs": len(runs),
                }
            )
            if not watch or campaign.status in _TERMINAL:
                break
            time.sleep(settings.runner.tick_interval_s)
    finally:
        services.close()


@app.command("run")
def run_cmd(
    ctx: typer.Context,
    config: Annotated[Path, typer.Argument(exists=True, dir_okay=False)],
    inline: Annotated[bool, typer.Option("--inline")] = False,
    workers: Annotated[int, typer.Option("--workers", min=1)] = 1,
    fail_on_failure: Annotated[bool, typer.Option("--fail-on-failure")] = False,
) -> None:
    """Create a campaign; with ``--inline`` drive it to completion in-process."""
    state = get_state(ctx)
    settings = state.bootstrap()
    if not inline:
        cid = create_campaign_from_config(config, settings)
        state.output.data({"campaign_id": str(cid), "inline": False})
        return
    settings = settings.model_copy(
        update={
            "worker": settings.worker.model_copy(
                update={"poll_interval_s": min(settings.worker.poll_interval_s, 0.05)}
            ),
            "runner": settings.runner.model_copy(
                update={"tick_interval_s": min(settings.runner.tick_interval_s, 0.05)}
            ),
            "observability": settings.observability.model_copy(update={"metrics_enabled": False}),
        }
    )
    cid = create_campaign_from_config(config, settings)
    status = run_inline(cid, settings, workers=workers)
    services = build_cli_services(settings)
    try:
        with services.make_uow() as uow:
            runs = _list_runs(uow, cid)
        fails = sum(1 for r in runs if _status_value(getattr(r, "verdict", "")) == "FAIL")
        state.output.data(
            {
                "campaign_id": str(cid),
                "status": status.value,
                "runs": len(runs),
                "failures": fails,
            }
        )
        if fail_on_failure and fails > 0:
            raise typer.Exit(3)  # docs/05 §11 FAILURES_FOUND
    finally:
        services.close()
