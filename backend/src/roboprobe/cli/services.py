"""Long-running service entry points: ``orchestrator``, ``worker``, ``api``.

Layer: Interface (L4). Options only — wiring lives in ``roboprobe.bootstrap``.

Implements: T-045c, FR-CLI-001
"""

from __future__ import annotations

import importlib
import threading
from typing import Annotated

import typer

from roboprobe.bootstrap import build_orchestrator, build_worker
from roboprobe.cli._context import get_state
from roboprobe.cli.space import REPO_ROOT
from roboprobe.core.errors import ValidationError
from roboprobe.runner.orchestrator import Orchestrator
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
    concurrency: Annotated[int, typer.Option("--concurrency", min=1)] = 1,
    space_id: Annotated[
        str, typer.Option("--space", help="Scenario space whose task the worker judges.")
    ] = "warehouse_v1",
) -> None:
    """Run one or more worker slots for ``backend``."""
    if ctx.invoked_subcommand is not None:
        return
    state = get_state(ctx)
    settings = state.bootstrap()
    settings = settings.model_copy(
        update={"worker": settings.worker.model_copy(update={"backend": backend})}
    )
    space = ScenarioSpace.from_yaml(
        REPO_ROOT / "configs" / "scenario_spaces" / f"{space_id}.yaml",
        base_dir=REPO_ROOT,
    )
    stop = threading.Event()
    threads: list[threading.Thread] = []
    workers = []
    try:
        for slot in range(concurrency):
            worker = build_worker(settings, task=space.task, slot=slot)
            workers.append(worker)
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
        state.output.data({"service": "worker", "backend": backend, "concurrency": concurrency})
        for thread in threads:
            thread.join()
    finally:
        stop.set()
        for worker in workers:
            worker.request_stop()


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
