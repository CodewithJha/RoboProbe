"""Frozen Pydantic value objects exchanged between modules (docs/05 §1, docs/06 §1, §7).

Implements: FR-ORC-002, FR-RUN-004
"""

from __future__ import annotations

from typing import Annotated, Literal, NamedTuple, Self
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from roboprobe.core.types.enums import FailureClass, Verdict

__all__ = [
    "CampaignSchedulingSnapshot",
    "GoalTolerance",
    "InjectedObstacle",
    "Observation",
    "ObstaclePlacement",
    "OracleResult",
    "ParamValue",
    "Phase",
    "Pose2D",
    "Proposal",
    "RunOutcome",
    "Scenario",
    "Severity",
    "SutProfile",
    "TaskField",
    "TaskSpec",
    "TimeLimitSpec",
]


class CampaignSchedulingSnapshot(NamedTuple):
    """Budget use, next ordinal, and in-flight unit vectors from one read."""

    budget_used: int
    next_ordinal: int
    inflight_vectors: tuple[tuple[float, ...], ...]


# --------------------------------------------------------------------------- aliases

Phase = Literal[
    "warmup",
    "falsify",
    "mode_search",
    "boundary",
    "refine",
    "explore",
    "baseline",
    "manual",
    "confirm",
    "replay",
]
"""Selection phase that produced a proposal (docs/11 ``runs.phase``)."""

TaskField = Literal[
    "world",
    "map",
    "start",
    "goal",
    "goal_tolerance",
    "nominal_path",
    "injected_obstacles",
    "time_limit",
]
"""Names of :class:`TaskSpec` fields that may be marked provisional."""

Severity = Literal["failure", "warning"]
"""Oracle severity: ``failure`` decides the verdict, ``warning`` is informational (docs/08)."""

ParamValue = float | int | str
"""Value of one scenario parameter, keyed by parameter id (e.g. ``"robot.max_speed"``)."""

Robustness = Annotated[float, Field(ge=-1.0, le=1.0)]
UnitInterval = Annotated[float, Field(ge=0.0, le=1.0)]
NonNegative = Annotated[float, Field(ge=0.0)]
Positive = Annotated[float, Field(gt=0.0)]
NonEmptyStr = Annotated[str, Field(min_length=1)]


class _Frozen(BaseModel):
    """Base for immutable value objects: frozen, no extra keys, finite floats only."""

    model_config = ConfigDict(frozen=True, extra="forbid", allow_inf_nan=False)


def _check_robustness_matches_verdict(verdict: Verdict, robustness: float | None) -> None:
    """Enforce the invariant ``robustness is None`` iff ``verdict == INVALID`` (docs/08 §3).

    Raises:
        ValueError: If the invariant is violated.
    """
    if (verdict is Verdict.INVALID) != (robustness is None):
        msg = "robustness must be None if and only if verdict is INVALID"
        raise ValueError(msg)


# --------------------------------------------------------------------------- scenario & selection


class Scenario(_Frozen):
    """One concrete point of a scenario space (docs/06 §8).

    Attributes:
        space_id: Scenario space identifier, e.g. ``"warehouse_v1"``.
        space_version: SHA-256 prefix of the canonical space YAML.
        values: Parameter values keyed by parameter id.
        scenario_hash: Canonical hash of the scenario (FR-SCN-006).
    """

    space_id: NonEmptyStr
    space_version: NonEmptyStr
    values: dict[str, ParamValue]
    scenario_hash: NonEmptyStr

    def __hash__(self) -> int:
        """Hash on identity fields; ``values`` is a dict and therefore unhashable."""
        return hash((self.space_id, self.space_version, self.scenario_hash))


class Proposal(_Frozen):
    """A scenario proposed by a selection strategy, with its rationale (docs/07)."""

    scenario: Scenario
    strategy: NonEmptyStr
    phase: Phase
    acquisition_value: float | None = None
    predicted_mean: float | None = None
    predicted_std: NonNegative | None = None
    tags: tuple[str, ...] = ()


class Observation(_Frozen):
    """What a strategy learns from one finished run (docs/07 §1).

    Attributes:
        x_unit: Normalised scenario in ``[0, 1]^d``.
        robustness: Robustness ``rho`` in ``[-1, 1]``; ``None`` iff the run is INVALID.
        verdict: Run verdict.
        failure_class: Primary failure class, if any.
        run_id: Identifier of the run that produced the observation.
    """

    x_unit: tuple[UnitInterval, ...]
    robustness: Robustness | None
    verdict: Verdict
    failure_class: FailureClass | None
    run_id: UUID

    @model_validator(mode="after")
    def _robustness_iff_valid(self) -> Self:
        _check_robustness_matches_verdict(self.verdict, self.robustness)
        return self


# --------------------------------------------------------------------------- judging


class OracleResult(_Frozen):
    """Result of one oracle evaluated on one trace (docs/08 §4)."""

    oracle_id: NonEmptyStr
    failure_class: FailureClass
    severity: Severity
    robustness: Robustness
    violated: bool
    first_violation_t: NonNegative | None
    details: dict[str, float | str]


class RunOutcome(_Frozen):
    """Aggregated verdict of a run (docs/08 §5); ``robustness`` is ``None`` iff INVALID."""

    verdict: Verdict
    robustness: Robustness | None
    primary_failure: FailureClass | None
    oracle_results: tuple[OracleResult, ...]
    metrics: dict[str, float]

    @model_validator(mode="after")
    def _robustness_iff_valid(self) -> Self:
        _check_robustness_matches_verdict(self.verdict, self.robustness)
        return self


# --------------------------------------------------------------------------- task & SUT


class Pose2D(_Frozen):
    """Planar pose: position in metres, heading ``yaw`` in radians."""

    x: float
    y: float
    yaw: float


class GoalTolerance(_Frozen):
    """Goal acceptance tolerances (docs/06 §1): position [m] and heading [rad]."""

    xy: Positive
    yaw: Positive


class TimeLimitSpec(_Frozen):
    """Episode time-limit formula ``min(factor * L / v_max + offset_s, cap_s)`` (docs/06 §1)."""

    factor: Positive
    offset_s: NonNegative
    cap_s: Positive


class ObstaclePlacement(_Frozen):
    """Where an injected obstacle goes, as references to scenario parameter ids (docs/06 §7)."""

    along: NonEmptyStr
    lateral: NonEmptyStr
    side: Literal["left", "right"]


class InjectedObstacle(_Frozen):
    """An obstacle injected along the nominal path; ``size`` is ``(x, y, z)`` in metres."""

    model: NonEmptyStr
    size: tuple[Positive, Positive, Positive]
    placement: ObstaclePlacement


class TaskSpec(_Frozen):
    """The navigation task under test (docs/06 §1, §7).

    Attributes:
        schema_version: Task file schema version.
        id: Task identifier, e.g. ``"warehouse_delivery_v1"``.
        name: Optional human-readable title.
        description: Optional free text.
        world: World file per backend name (e.g. ``{"kinematic2d": "worlds/..."}``).
        map: Occupancy map reference.
        start: Start pose.
        goal: Goal pose.
        goal_tolerance: Goal acceptance tolerances.
        nominal_path: Reference to the stored nominal path polyline.
        injected_obstacles: Obstacles placed relative to the nominal path.
        time_limit: Time-limit formula parameters.
        provisional: Fields holding provisional values awaiting verification (e.g. a goal
            picked on the kinematic2d world before the Gazebo map check, T-092).
    """

    schema_version: Annotated[int, Field(ge=1)]
    id: NonEmptyStr
    name: str | None = None
    description: str | None = None
    world: dict[str, NonEmptyStr]
    map: NonEmptyStr
    start: Pose2D
    goal: Pose2D
    goal_tolerance: GoalTolerance
    nominal_path: NonEmptyStr
    injected_obstacles: tuple[InjectedObstacle, ...] = ()
    time_limit: TimeLimitSpec
    provisional: tuple[TaskField, ...] = ()


class SutProfile(_Frozen):
    """System-under-test configuration profile (docs/11 ``sut_profiles``)."""

    id: NonEmptyStr
    backend: NonEmptyStr
    config: dict[str, JsonValue]
    config_hash: NonEmptyStr
