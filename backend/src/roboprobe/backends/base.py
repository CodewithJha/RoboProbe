"""SimulatorBackend port, capabilities and episode DTOs (docs/05 §2.1).

Implements: FR-RUN-006, NFR-EXT-001, PR-19
"""

from __future__ import annotations

from collections.abc import Callable, Collection
from pathlib import Path
from typing import ClassVar, Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from roboprobe.core import errors
from roboprobe.core.settings.worker import WorkerSettings
from roboprobe.core.types import JsonValue, Scenario, SutProfile, TaskSpec, Trace

__all__ = [
    "PLUGIN_API_VERSION",
    "BackendCapabilities",
    "EpisodeRequest",
    "EpisodeResult",
    "MaterializedScenario",
    "SimulatorBackend",
    "assert_supports",
    "episode_timeouts",
]

PLUGIN_API_VERSION: int = 1
"""Entry-point backends must declare this :attr:`SimulatorBackend.PLUGIN_API_VERSION`."""


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid", arbitrary_types_allowed=True)


class BackendCapabilities(_Frozen):
    """What a backend can simulate (docs/05 §2.1)."""

    name: str
    supported_params: frozenset[str]
    deterministic: bool
    typical_episode_wall_s: float
    max_parallel_per_host: int


class EpisodeRequest(_Frozen):
    """One episode to materialise and run."""

    run_id: UUID
    scenario: Scenario
    task: TaskSpec
    sut_profile: SutProfile
    seed: int
    workdir: Path
    sim_time_budget_s: float
    wall_timeout_s: float
    record_bag: bool = False


class EpisodeResult(_Frozen):
    """Outcome of :meth:`SimulatorBackend.run_episode`."""

    trace: Trace
    artifacts: dict[str, Path]
    backend_meta: dict[str, str]
    infra_error: str | None = None


class MaterializedScenario(_Frozen):
    """Deterministic files written by :meth:`SimulatorBackend.materialize` (FR-SCN-005)."""

    files: dict[str, Path] = Field(default_factory=dict)
    payload: dict[str, JsonValue] = Field(default_factory=dict)


class SimulatorBackend(Protocol):
    """Swap point for kinematic2d, Gazebo and replay (docs/10 §1)."""

    PLUGIN_API_VERSION: ClassVar[int]
    capabilities: BackendCapabilities

    def prepare(self) -> None:
        """One-time per worker (pull images, warm caches)."""
        ...

    def materialize(self, req: EpisodeRequest) -> MaterializedScenario:
        """Write scenario files into ``req.workdir`` (pure given equal inputs)."""
        ...

    def run_episode(
        self,
        req: EpisodeRequest,
        materialized: MaterializedScenario,
        on_progress: Callable[[float], None] | None = None,
    ) -> EpisodeResult:
        """Run one episode; infrastructure failures go in ``EpisodeResult.infra_error``."""
        ...

    def cancel(self) -> None:
        """Best-effort cooperative cancel of the in-flight episode."""
        ...

    def shutdown(self) -> None:
        """Release worker-local resources."""
        ...


def episode_timeouts(worker: WorkerSettings) -> tuple[float, float]:
    """``(sim_time_budget_s, wall_timeout_s)`` from worker settings (docs/05 §0)."""
    return worker.default_sim_time_budget_s, worker.default_wall_timeout_s


def assert_supports(capabilities: BackendCapabilities, enabled_params: Collection[str]) -> None:
    """Raise if any enabled parameter is outside ``capabilities.supported_params``.

    Raises:
        roboprobe.core.errors.ValidationError: Code ``BACKEND_UNSUPPORTED_PARAM``.
    """
    unsupported = sorted(set(enabled_params) - set(capabilities.supported_params))
    if not unsupported:
        return
    msg = (
        f"backend {capabilities.name!r} does not support parameters {unsupported}; "
        "disable them in the space or pick another backend"
    )
    raise errors.ValidationError(
        msg,
        code=errors.ErrorCode.BACKEND_UNSUPPORTED_PARAM,
        context={
            "backend": capabilities.name,
            "unsupported": list(unsupported),
        },
    )
