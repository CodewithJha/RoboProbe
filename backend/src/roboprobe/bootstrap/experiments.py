"""Wire registered or planned experiments to the real campaign runner (T-084a)."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from threading import Event
from uuid import UUID, uuid4

import structlog

from roboprobe.bootstrap._infra import UowFactory
from roboprobe.core.clock import SystemClock
from roboprobe.core.errors import NotFoundError
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.core.types import CampaignStatus, JsonValue
from roboprobe.experiments.comparison import read_campaign_runs
from roboprobe.experiments.planner import CampaignSpec, ComparabilityKey, ExperimentDesign
from roboprobe.experiments.runner import ExperimentRunner
from roboprobe.metrics.campaign_metrics import CampaignRun
from roboprobe.runner.lifecycle import CampaignService
from roboprobe.store.records import CampaignRecord, ExperimentRecord

__all__ = ["ExperimentJobs", "SqlExperimentWriter"]

log = structlog.get_logger(__name__)
_TERMINAL = {CampaignStatus.COMPLETED, CampaignStatus.FAILED, CampaignStatus.CANCELLED}


class SqlExperimentWriter:
    """Persist experiment state through the same unit of work as CLI campaigns."""

    def __init__(self, make_uow: UowFactory) -> None:
        """Inject the database transaction factory."""
        self._make_uow = make_uow

    def add_experiment(self, *, name: str, design: dict[str, JsonValue], status: str) -> UUID:
        """Store a new experiment."""
        experiment_id = uuid4()
        with self._make_uow() as uow:
            uow.experiments.add(
                ExperimentRecord(id=experiment_id, name=name, design=design, status=status)
            )
        return experiment_id

    def add_campaign(self, spec: CampaignSpec, experiment_id: UUID) -> UUID:
        """Create one campaign for a CLI experiment."""
        campaign_id = uuid4()
        with self._make_uow() as uow:
            uow.campaigns.add(
                CampaignRecord(
                    id=campaign_id,
                    name=spec.name,
                    space_id=spec.space_id,
                    space_version=spec.space_version,
                    sut_profile_id=spec.sut_profile_id or "k2d_default",
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
        return campaign_id

    def get_experiment(self, experiment_id: UUID) -> ExperimentRecord | None:
        """Retrieve an experiment and its stored comparison."""
        with self._make_uow() as uow:
            return uow.experiments.get(experiment_id)

    def set_experiment_status(
        self, experiment_id: UUID, status: str, *, finished: bool = False
    ) -> None:
        """Persist the current experiment state."""
        del finished
        with self._make_uow() as uow:
            uow.experiments.set_status(experiment_id, status)

    def set_experiment_results(self, experiment_id: UUID, results: dict[str, JsonValue]) -> None:
        """Persist the comparison returned by the experiment runner."""
        with self._make_uow() as uow:
            uow.experiments.set_results(experiment_id, dict[str, object](results))

    def list_campaigns(self, experiment_id: UUID) -> list[object]:
        """Read the campaigns created from the experiment matrix."""
        with self._make_uow() as uow:
            return list(uow.campaigns.list_for_experiment(experiment_id))

    def campaign_runs(self, campaign_id: UUID) -> list[CampaignRun]:
        """Load all proposal-ordered observations before computing statistics."""
        with self._make_uow() as uow:
            return read_campaign_runs(uow.runs, campaign_id)


class _ShuttingDownError(Exception):
    """Stop waiting for a worker when the API process is shutting down."""


class ExperimentJobs:
    """Drive API-created experiment cells with the orchestrator and configured workers."""

    def __init__(
        self,
        make_uow: UowFactory,
        settings: RoboProbeSettings,
        campaigns: CampaignService,
    ) -> None:
        """Inject campaign lifecycle, storage and executor settings."""
        self._make_uow = make_uow
        self._writer = SqlExperimentWriter(make_uow)
        self._campaigns = campaigns
        self._poll_interval = settings.worker.poll_interval_s
        self._stopping = Event()
        self._executor = ThreadPoolExecutor(max_workers=settings.api.experiment_workers)
        self._runner = ExperimentRunner(
            self._writer, settings.experiments, SystemClock(), self._drive, new_uuid=uuid4
        )

    def submit(self, experiment_id: UUID, design: ExperimentDesign, key: ComparabilityKey) -> None:
        """Queue a planned experiment after its transaction has committed."""
        self._executor.submit(self._execute, experiment_id, design, key)

    def close(self) -> None:
        """Stop waiting for external workers before disposing the shared database engine."""
        self._stopping.set()
        self._executor.shutdown(wait=True, cancel_futures=True)

    def _execute(
        self, experiment_id: UUID, design: ExperimentDesign, key: ComparabilityKey
    ) -> None:
        try:
            self._runner.start(design, key, experiment_id=experiment_id)
        except _ShuttingDownError:
            return
        except Exception as exc:
            self._writer.set_experiment_status(experiment_id, "FAILED", finished=True)
            log.warning(
                "experiment.launch_failed",
                experiment_id=str(experiment_id),
                error=type(exc).__name__,
            )

    def _drive(self, campaign_id: UUID) -> CampaignStatus:
        self._campaigns.start(campaign_id)
        while not self._stopping.is_set():
            with self._make_uow() as uow:
                row = uow.campaigns.get(campaign_id)
                if row is None:
                    msg = "experiment campaign not found"
                    raise NotFoundError(msg, context={"campaign_id": str(campaign_id)})
                if row.status in _TERMINAL:
                    return row.status
            self._stopping.wait(self._poll_interval)
        raise _ShuttingDownError
