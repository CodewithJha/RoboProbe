"""Experiment design loading and campaign planning with CRN seeds (docs/14 §8, docs/33 §6).

Implements: T-102a, FR-EXP-001, PR-10
"""

from __future__ import annotations

from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

from roboprobe.core import errors
from roboprobe.core.seeding import REP, derive_seed
from roboprobe.scenario._documents import load_yaml_document, validate_document

__all__ = [
    "CampaignSpec",
    "ComparabilityKey",
    "ExperimentDesign",
    "StrategyVariant",
    "check_comparable",
    "load_design",
    "plan",
]

_SCHEMA = "experiment"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class ComparabilityKey(_Frozen):
    """Versions that must match for a valid strategy comparison (docs/33 §6)."""

    space_version: str
    oracle_set_version: str
    sut_config_hash: str
    backend_version: str
    k2d_model_version: str


class StrategyVariant(_Frozen):
    """One strategy (or named ablation) in an experiment matrix."""

    id: str
    label: str | None = None
    params: dict[str, Any] = Field(default_factory=dict)

    @property
    def display_label(self) -> str:
        """Report label: explicit variant name, else the strategy id."""
        return self.label if self.label is not None else self.id


class _SpaceRef(_Frozen):
    id: str
    version: str | None = None


class _SeedsSpec(_Frozen):
    root: int
    count: int | None = None


class ExperimentDesign(_Frozen):
    """Parsed experiment YAML (``schemas/experiment.schema.json``)."""

    schema_version: Literal[1]
    id: str
    name: str | None = None
    description: str | None = None
    backend: str
    space: _SpaceRef
    sut_profile_id: str | None = None
    strategies: tuple[StrategyVariant, ...]
    seeds: _SeedsSpec
    budget: int
    repeats: int = 1
    batch_size: int = 1
    pins: dict[str, Any] = Field(default_factory=dict)
    oracle_overrides: dict[str, Any] = Field(default_factory=dict)
    stop_rules: dict[str, Any] = Field(default_factory=dict)
    metrics: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()

    @field_validator("strategies", mode="before")
    @classmethod
    def _tuple_strategies(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value

    @field_validator("metrics", "tags", mode="before")
    @classmethod
    def _tuple_str_seq(cls, value: object) -> object:
        return tuple(value) if isinstance(value, list) else value


class CampaignSpec(_Frozen):
    """One campaign to create for a strategy x seed cell."""

    experiment_id: str
    experiment_rep: int
    name: str
    strategy_id: str
    strategy_label: str
    strategy_params: dict[str, Any]
    seed: int
    budget: int
    repeats: int
    batch_size: int
    backend: str
    space_id: str
    space_version: str
    sut_profile_id: str | None
    pins: dict[str, Any]
    oracle_overrides: dict[str, Any]
    stop_rules: dict[str, Any]
    tags: tuple[str, ...]
    metrics: tuple[str, ...]
    comparability: ComparabilityKey


def load_design(path: Path) -> ExperimentDesign:
    """Load and schema-validate an experiment YAML file.

    Args:
        path: Path to ``configs/experiments/*.yaml``.

    Returns:
        Validated :class:`ExperimentDesign`.

    Raises:
        roboprobe.core.errors.ValidationError: On YAML or schema errors.
        roboprobe.core.errors.NotFoundError: If ``path`` is missing.
    """
    try:
        text = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        msg = f"file not found: {path}"
        raise errors.NotFoundError(msg, context={"path": str(path)}) from exc
    source = str(path)
    document = load_yaml_document(text, source=source)
    validate_document(document, schema=_SCHEMA, source=source)
    if not isinstance(document, dict):
        msg = f"{source} must be a mapping"
        raise errors.ValidationError(msg, context={"source": source})
    return ExperimentDesign.model_validate(document)


def check_comparable(*keys: ComparabilityKey) -> None:
    """Reject mismatched version fingerprints (docs/33 §6).

    Raises:
        roboprobe.core.errors.ValidationError: If any key differs from the first.
    """
    if not keys:
        return
    ref = keys[0]
    for other in keys[1:]:
        mismatched = [
            name
            for name in ComparabilityKey.model_fields
            if getattr(other, name) != getattr(ref, name)
        ]
        if mismatched:
            msg = "experiment comparability rule violated"
            raise errors.ValidationError(
                msg,
                context={
                    "mismatched": ", ".join(mismatched),
                    "expected": ref.model_dump(),
                    "actual": other.model_dump(),
                },
            )


def plan(
    design: ExperimentDesign,
    *,
    default_seeds: int,
    key: ComparabilityKey,
) -> list[CampaignSpec]:
    """Expand ``design`` into campaign specs with common-random-number seeds.

    ``campaign_seed = derive_seed(experiment_seed, 'rep', k)`` is shared across strategies for
    the same replicate index ``k`` (docs/14 §8, docs/21 §3).

    Args:
        design: Validated experiment design.
        default_seeds: ``experiments.default_seeds`` when ``seeds.count`` is omitted.
        key: Resolved version fingerprint stamped onto every campaign.

    Returns:
        Deterministic list ordered by strategy then replicate index.

    Raises:
        roboprobe.core.errors.ValidationError: If ``space.version`` disagrees with ``key``.
    """
    if design.space.version is not None and design.space.version != key.space_version:
        msg = "experiment space.version does not match comparability key"
        raise errors.ValidationError(
            msg,
            context={
                "space.version": design.space.version,
                "key.space_version": key.space_version,
            },
        )
    count = design.seeds.count if design.seeds.count is not None else default_seeds
    specs: list[CampaignSpec] = []
    for variant in design.strategies:
        label = variant.display_label
        for rep in range(count):
            seed = derive_seed(design.seeds.root, REP, rep)
            specs.append(
                CampaignSpec(
                    experiment_id=design.id,
                    experiment_rep=rep,
                    name=f"{design.id}:{label}:rep{rep}",
                    strategy_id=variant.id,
                    strategy_label=label,
                    strategy_params=dict(variant.params),
                    seed=seed,
                    budget=design.budget,
                    repeats=design.repeats,
                    batch_size=design.batch_size,
                    backend=design.backend,
                    space_id=design.space.id,
                    space_version=key.space_version,
                    sut_profile_id=design.sut_profile_id,
                    pins=dict(design.pins),
                    oracle_overrides=dict(design.oracle_overrides),
                    stop_rules=dict(design.stop_rules),
                    tags=design.tags,
                    metrics=design.metrics,
                    comparability=key,
                )
            )
    return specs
