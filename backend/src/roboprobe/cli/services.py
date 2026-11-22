"""Long-running service entry points: ``orchestrator``, ``worker``, ``api``.

Layer: Interface (L4). Options only — wiring lives in ``roboprobe.bootstrap``.

Implements: T-045c, FR-CLI-001
"""

from __future__ import annotations

import importlib
import threading
from queue import SimpleQueue
from typing import Annotated

import typer

from roboprobe.bootstrap import build_cli_services, build_orchestrator, build_worker
from roboprobe.bootstrap.worker import worker_slot_count
from roboprobe.cli._context import get_state
from roboprobe.cli.space import REPO_ROOT
from roboprobe.core.clock import SystemClock
from roboprobe.core.errors import RoboProbeError, ValidationError
from roboprobe.core.metrics_registry import create_metrics
from roboprobe.runner.heartbeat import HeartbeatService
from roboprobe.runner.orchestrator import Orchestrator
from roboprobe.runner.worker import WorkerProcess
from roboprobe.scenario.space import ScenarioSpace

__all__ = ["api_app", "orchestrator_app", "worker_app"]

orchestrator_app = typer.Typer(
    name="orchestrator",
    help="Run the multi-campaign orchestrator.",
    invoke_without_command=True,
)
worker_app = typer.Typer(
    name="worker",
    help="Run simulation worker slot(s).",
    invoke_without_command=True,
)
api_app = typer.Typer(
    name="api",
    help="Serve the HTTP API.",
    invoke_without_command=True,
)


@orchestrator_app.callback(invoke_without_command=True)
def orchestrator_cmd(ctx: typer.Context) -> None:
    """Run the multi-campaign orchestrator supervisor."""
    if ctx.invoked_subcommand is not None:
        return
    state = get_state(ctx)
    settings = state.bootstrap()
    services = build_orchestrator(settings)
    orch = Orchestrator(
        settings=services.settings,
        uow_factory=services.uow_factory,
        clock=services.clock,
        metrics=services.metrics,
        campaigns=services.campaigns,
        reaper=services.reaper,
        scheduler=services.scheduler,
        engine=services.infra.engine,
        space_root=REPO_ROOT,
    )
    stop = threading.Event()
    try:
        state.output.data({"service": "orchestrator", "status": "starting"})
        orch.serve_forever(stop)
    finally:
        orch.request_stop()
        services.close()


@worker_app.callback(invoke_without_command=True)
def worker_cmd(
    ctx: typer.Context,
    backend: Annotated[str, typer.Option("--backend", help="Simulator backend id.")],
    concurrency: Annotated[int | None, typer.Option("--concurrency", min=1)] = None,
    space_id: Annotated[
        str, typer.Option("--space", help="Scenario space whose task the worker judges.")
    ] = "warehouse_v1",
    health: Annotated[
        bool, typer.Option("--health", help="Serve the worker health endpoint.")
    ] = False,
) -> None:
    """Run one or more worker slots for ``backend``."""
    if ctx.invoked_subcommand is not None:
        return
    state = get_state(ctx)
    settings = state.bootstrap()
    settings = settings.model_copy(
        update={"worker": settings.worker.model_copy(update={"backend": backend})}
    )
    requested = settings.worker.concurrency if concurrency is None else concurrency
    concurrency = worker_slot_count(settings, requested)
    space = ScenarioSpace.from_yaml(
        REPO_ROOT / "configs" / "scenario_spaces" / f"{space_id}.yaml",
        base_dir=REPO_ROOT,
    )
    services = build_cli_services(settings)
    clock = SystemClock()
    metrics = create_metrics(enabled=settings.observability.metrics_enabled)
    stop = threading.Event()
    threads: list[threading.Thread] = []
    heartbeats: list[HeartbeatService] = []
    workers = []
    worker_errors: SimpleQueue[RoboProbeError] = SimpleQueue()

    def serve_worker(worker: WorkerProcess) -> None:
        try:
            worker.serve_forever(stop)
        except RoboProbeError as exc:
            worker_errors.put(exc)
            stop.set()

    try:
        for slot in range(concurrency):
            slot_settings = settings.worker.model_copy(
                update={"health_port": settings.worker.health_port + slot}
            )
            worker = build_worker(
                settings.model_copy(update={"worker": slot_settings}),
                task=space.task,
                slot=slot,
                infra=services.infra,
            )
            workers.append(worker)
            heartbeat = HeartbeatService(
                worker=worker,
                uow_factory=services.uow_factory,
                clock=clock,
                settings=slot_settings,
                retry=settings.runner.retry,
                heartbeat_timeout_s=settings.runner.heartbeat_timeout_s,
                metrics=metrics,
            )
            heartbeats.append(heartbeat)
            heartbeat.register()
            heartbeat.start(serve_probe=health)
            threads.append(
                threading.Thread(
                    target=serve_worker,
                    args=(worker,),
                    name=f"worker-{slot}",
                    daemon=True,
                )
            )
        for thread in threads:
            thread.start()
        state.output.data({"service": "worker", "backend": backend, "concurrency": concurrency})
        for thread in threads:
            thread.join()
        if not worker_errors.empty():
            raise worker_errors.get()
    finally:
        stop.set()
        for worker in workers:
            worker.request_stop()
        for heartbeat in heartbeats:
            heartbeat.stop()
        services.close()


@api_app.callback(invoke_without_command=True)
def api_cmd(
    ctx: typer.Context,
    host: Annotated[str | None, typer.Option("--host")] = None,
    port: Annotated[int | None, typer.Option("--port")] = None,
) -> None:
    """Serve the HTTP API (requires the ``api`` extra)."""
    if ctx.invoked_subcommand is not None:
        return
    state = get_state(ctx)
    settings = state.bootstrap()
    bind_host = host if host is not None else settings.api.host
    bind_port = port if port is not None else settings.api.port
    if host is not None or port is not None:
        settings = settings.model_copy(
            update={
                "api": settings.api.model_copy(
                    update={
                        **({"host": bind_host} if host is not None else {}),
                        **({"port": bind_port} if port is not None else {}),
                    }
                )
            }
        )
    try:
        uvicorn = importlib.import_module("uvicorn")
        bootstrap_api = importlib.import_module("roboprobe.bootstrap.api")
    except ModuleNotFoundError as exc:
        msg = "API dependencies missing; install the api extra (pip/uv install 'roboprobe[api]')"
        raise ValidationError(msg) from exc
    app = bootstrap_api.create_api_app(settings)
    state.output.data({"service": "api", "host": bind_host, "port": bind_port})
    # The application logs requests with redaction. Uvicorn logs the raw SSE query string.
    uvicorn.run(app, host=bind_host, port=bind_port, log_level="info", access_log=False)
