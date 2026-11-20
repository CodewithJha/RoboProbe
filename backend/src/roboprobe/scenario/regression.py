"""Standalone regression scenario YAML export and import (docs/06 §6).

Implements: FR-SCN-008, PR-08
"""

from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Annotated
from uuid import UUID

import yaml
from pydantic import BaseModel, ConfigDict, Field

from roboprobe.core import errors
from roboprobe.core.types import FailureClass, ParamValue, Scenario, Verdict
from roboprobe.scenario import hashing
from roboprobe.scenario._documents import (
    load_yaml_document,
    read_document,
    validate_document,
)
from roboprobe.scenario.space import ScenarioSpace

__all__ = [
    "EXPECT_KEY_ORDER",
    "EXPORT_KEY_ORDER",
    "PROVENANCE_KEY_ORDER",
    "RegressionExpect",
    "RegressionProvenance",
    "RegressionScenario",
    "export_regression",
    "load_regression",
]

_KIND = "scenario"
_SCHEMA_VERSION = 1
_SCHEMA_NAME = "scenario"
_SPACE_UPGRADE_HINT = "run `roboprobe space upgrade` after aligning the space file"


class _Frozen(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")


class RegressionExpect(_Frozen):
    """Expected judgement recorded for regression CI (docs/06 §6)."""

    verdict: Verdict
    failure_class: FailureClass | None = None


class RegressionProvenance(_Frozen):
    """Optional origin of an exported regression file."""

    source_run: UUID | None = None
    failure_mode: Annotated[str, Field(min_length=1)] | None = None
    exported_at: datetime | None = None


class RegressionScenario(_Frozen):
    """A scenario plus optional seed, expect block and provenance."""

    scenario: Scenario
    seed: Annotated[int, Field(ge=0)] | None = None
    expect: RegressionExpect | None = None
    provenance: RegressionProvenance | None = None


EXPORT_KEY_ORDER: tuple[str, ...] = (
    "schema_version",
    "kind",
    "space",
    "values",
    "seed",
    "expect",
    "provenance",
)
"""Fixed top-level key order of an exported regression YAML file."""

PROVENANCE_KEY_ORDER: tuple[str, ...] = ("source_run", "failure_mode", "exported_at")
EXPECT_KEY_ORDER: tuple[str, ...] = ("verdict", "failure_class")


def export_regression(
    scenario: Scenario,
    seed: int | None,
    provenance: RegressionProvenance | None,
    expect: RegressionExpect | None,
) -> str:
    """Serialise ``scenario`` to regression YAML (schema ``scenario.schema.json``).

    Key order is :data:`EXPORT_KEY_ORDER`. Optional blocks are omitted when empty.
    """
    document: dict[str, object] = {
        "schema_version": _SCHEMA_VERSION,
        "kind": _KIND,
        "space": {"id": scenario.space_id, "version": scenario.space_version},
        "values": dict(scenario.values),
    }
    if seed is not None:
        document["seed"] = seed
    if expect is not None:
        block: dict[str, object] = {"verdict": expect.verdict.value}
        if expect.failure_class is not None:
            block["failure_class"] = expect.failure_class.value
        document["expect"] = block
    if provenance is not None:
        document["provenance"] = _provenance_dict(provenance)
    validate_document(document, schema=_SCHEMA_NAME, source="<export>")
    return yaml.safe_dump(document, sort_keys=False, allow_unicode=True)


def load_regression(path: Path, *, space: ScenarioSpace | None = None) -> RegressionScenario:
    """Load a regression YAML file into a :class:`RegressionScenario`.

    Args:
        path: Regression file.
        space: When given, its id/version must match the file (else a space-upgrade error).

    Raises:
        roboprobe.core.errors.NotFoundError: If ``path`` does not exist.
        roboprobe.core.errors.ValidationError: On schema, hash or space-version mismatch.
    """
    source = str(path)
    document = load_yaml_document(read_document(path), source=source)
    validate_document(document, schema=_SCHEMA_NAME, source=source)
    if not isinstance(document, dict):
        msg = f"{source} is not a mapping"
        raise errors.ValidationError(msg, context={"source": source})
    space_ref = document["space"]
    space_id = str(space_ref["id"])
    space_version = str(space_ref.get("version", ""))
    if space is not None:
        _check_space(source, space, space_id, space_version)
    values: dict[str, ParamValue] = dict(document["values"])
    scenario = Scenario(
        space_id=space_id,
        space_version=space_version,
        values=values,
        scenario_hash=hashing.scenario_hash(space_version, values),
    )
    expect_raw = document.get("expect")
    expect = None
    if isinstance(expect_raw, dict):
        expect = RegressionExpect.model_validate(expect_raw)
    prov_raw = document.get("provenance")
    provenance = None
    if isinstance(prov_raw, dict):
        provenance = RegressionProvenance.model_validate(prov_raw)
    seed = document.get("seed")
    return RegressionScenario(
        scenario=scenario,
        seed=int(seed) if seed is not None else None,
        expect=expect,
        provenance=provenance,
    )


def _check_space(source: str, space: ScenarioSpace, space_id: str, space_version: str) -> None:
    if space.id != space_id:
        msg = f"{source}: space id {space_id!r} does not match {space.id!r}"
        raise errors.ValidationError(msg, context={"source": source, "space_id": space_id})
    if space.version != space_version:
        msg = (
            f"{source}: space version {space_version!r} does not match current "
            f"{space.version!r}; {_SPACE_UPGRADE_HINT}"
        )
        raise errors.ValidationError(
            msg,
            context={
                "source": source,
                "file_version": space_version,
                "current_version": space.version,
            },
        )


def _provenance_dict(provenance: RegressionProvenance) -> dict[str, object]:
    payload: dict[str, object] = {}
    if provenance.source_run is not None:
        payload["source_run"] = str(provenance.source_run)
    if provenance.failure_mode is not None:
        payload["failure_mode"] = provenance.failure_mode
    if provenance.exported_at is not None:
        payload["exported_at"] = provenance.exported_at.strftime("%Y-%m-%dT%H:%M:%SZ")
    return payload
