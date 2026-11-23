"""Offline MET-02 and MET-09 for EXP-07 from reviewed kinematic2d references."""

from __future__ import annotations

import re
from collections import defaultdict
from pathlib import Path
from typing import Annotated, Literal

import pyarrow.parquet as pq
from pydantic import BaseModel, ConfigDict, Field, JsonValue, TypeAdapter
from pydantic import ValidationError as PydanticValidationError

from roboprobe.bootstrap.reference_set import ReferenceManifest, read_reviewed_labels, sha256_file
from roboprobe.core.errors import ValidationError
from roboprobe.core.settings.experiments import ExperimentSettings
from roboprobe.experiments.planner import load_design
from roboprobe.metrics.discovery_metrics import NOVEL_LABEL, discovery_auc, label_failures
from roboprobe.scenario.repo_root import discover_repo_root

__all__ = ["score_reference"]

_EXP07_CONFIGS = {
    "exp07_scalability": "exp07_scalability.yaml",
    "exp07_noise2": "exp07_scalability_noise2.yaml",
    "exp07_d8": "exp07_scalability_d8.yaml",
}
_UNREVIEWED = "unreviewed"
_REVIEWED_NO_MODE = "reviewed-no-mode"
type _Unit = Annotated[float, Field(ge=0.0, le=1.0, allow_inf_nan=False)]
type _Ordinal = Annotated[int, Field(ge=0)]
type _Verdict = Literal["PASS", "FAIL", "INVALID"]


class _RunManifest(BaseModel):
    model_config = ConfigDict(strict=True)

    sha256: str
    config_sha256: str
    design_id: str
    backend: Literal["kinematic2d"]
    space_id: str
    space_version: Annotated[str, Field(min_length=1)]
    k2d_model_version: Annotated[str, Field(min_length=1)]
    budget: Annotated[int, Field(gt=0)]


class _Run(BaseModel):
    model_config = ConfigDict(strict=True)

    strategy: Annotated[str, Field(min_length=1)]
    experiment_rep: _Ordinal
    ordinal: _Ordinal
    verdict: _Verdict
    is_comparison_run: bool
    x_unit: list[_Unit]


def _read_reference(path: Path, manifest: ReferenceManifest) -> dict[int, list[float]]:
    table = pq.read_table(path)
    columns = [name for name in table.column_names if re.fullmatch(r"u[0-9]+", name)]
    unit_cols = [f"u{i}" for i in range(len(columns))]
    if not unit_cols or set(columns) != set(unit_cols) or table.num_rows != manifest.n:
        msg = "reference coordinates or row count do not match the manifest"
        raise ValidationError(msg)

    ordinals = TypeAdapter(list[_Ordinal]).validate_python(
        table["ordinal"].to_pylist(), strict=True
    )
    if set(ordinals) != set(range(manifest.n)):
        msg = "reference ordinals must identify every original row exactly once"
        raise ValidationError(msg)
    verdicts = TypeAdapter(list[_Verdict]).validate_python(table["verdict"].to_pylist())
    points = zip(*(table[name].to_pylist() for name in unit_cols), strict=True)
    values = TypeAdapter(list[list[_Unit]]).validate_python(list(points))
    return {
        ordinal: point
        for ordinal, verdict, point in zip(ordinals, verdicts, values, strict=True)
        if verdict == "FAIL"
    }


def _cells(runs: list[_Run], matches: list[str], *, budget: int, n_modes: int) -> list[JsonValue]:
    by_cell: dict[tuple[str, int], list[_Run]] = defaultdict(list)
    for run in runs:
        by_cell[run.strategy, run.experiment_rep].append(run)
    found = iter(matches)
    cells: list[JsonValue] = []
    for (strategy, rep), rows in sorted(by_cell.items()):
        if [run.ordinal for run in rows] != list(range(len(rows))):
            msg = "experiment rows must have unique, contiguous proposal ordinals per cell"
            raise ValidationError(msg, context={"strategy": strategy, "experiment_rep": rep})
        labels = [
            next(found) if run.verdict == "FAIL" else None for run in rows if run.is_comparison_run
        ]
        modes = sorted({label for label in labels if label and label.startswith("GT-")})
        unreviewed = labels.count(_UNREVIEWED)
        complete = len(labels) == budget and unreviewed == 0
        cells.append(
            {
                "strategy": strategy,
                "experiment_rep": rep,
                "comparison_runs": len(labels),
                "modes": list[JsonValue](modes),
                "novel_failures": labels.count(NOVEL_LABEL),
                "unreviewed_matches": unreviewed,
                "met_02": len(modes) if complete else None,
                "met_09": (
                    discovery_auc([label if label in modes else None for label in labels], n_modes)
                    if complete and n_modes
                    else None
                ),
            }
        )
    return cells


def score_reference(
    raw: Path, run_manifest: Path, reference: Path, review: Path | None = None
) -> dict[str, JsonValue]:
    """Score exported EXP-07 cells against a reference from the exact same space and model."""
    reference_manifest = reference.with_suffix(".manifest.json")
    try:
        collected = _RunManifest.model_validate_json(run_manifest.read_bytes())
        config = (
            discover_repo_root() / "configs" / "experiments" / _EXP07_CONFIGS[collected.design_id]
        )
        design = load_design(config)
        frozen = (sha256_file(config), design.id, design.budget)
        if (collected.config_sha256, collected.design_id, collected.budget) != frozen:
            msg = "run manifest differs from the frozen EXP-07 design digest or budget"
            raise ValidationError(msg)
        ref = TypeAdapter(ReferenceManifest).validate_json(reference_manifest.read_bytes())
        if collected.sha256 != sha256_file(raw) or ref.sha256 != sha256_file(reference):
            msg = "experiment or reference Parquet digest differs from its manifest"
            raise ValidationError(msg)
        if (
            design.space.id != collected.space_id
            or collected.space_id != ref.space_id
            or collected.space_version != ref.space_version
            or collected.k2d_model_version != ref.k2d_model_version
        ):
            msg = "EXP-07 arm does not match the exact reference space and model"
            raise ValidationError(msg)
        failing_ref = _read_reference(reference, ref)
        labels = read_reviewed_labels(review, ref.sha256) if review is not None else {}
        runs = TypeAdapter(list[_Run]).validate_python(pq.read_table(raw).to_pylist())
    except (PydanticValidationError, OSError, ValueError, KeyError) as exc:
        msg = "invalid EXP-07 run or reference artifact"
        raise ValidationError(msg) from exc

    if labels.keys() - failing_ref.keys():
        msg = "reviewed labels must refer only to failing reference rows"
        raise ValidationError(msg)
    if not runs or not failing_ref:
        msg = "EXP-07 scoring needs experiment rows and a failing reference inventory"
        raise ValidationError(msg)
    runs.sort(key=lambda run: (run.strategy, run.experiment_rep, run.ordinal))
    unit_failures = [run.x_unit for run in runs if run.is_comparison_run and run.verdict == "FAIL"]
    dimension = len(next(iter(failing_ref.values())))
    if any(len(point) != dimension for point in unit_failures):
        msg = "experiment and reference unit coordinate dimensions differ"
        raise ValidationError(msg)
    radius = ExperimentSettings().mode_match_radius
    ordinals = sorted(failing_ref)
    ref_modes = [
        labels.get(ordinal) or (_REVIEWED_NO_MODE if ordinal in labels else _UNREVIEWED)
        for ordinal in ordinals
    ]
    matches = label_failures(unit_failures, [failing_ref[i] for i in ordinals], ref_modes, radius)
    unreviewed = len(failing_ref) - len(labels)
    modes = sorted({mode for mode in labels.values() if mode is not None})
    return {
        "design_id": design.id,
        "config_sha256": collected.config_sha256,
        "space_id": collected.space_id,
        "space_version": collected.space_version,
        "k2d_model_version": collected.k2d_model_version,
        "budget": design.budget,
        "mode_match_radius": radius,
        "raw_sha256": collected.sha256,
        "reference_sha256": ref.sha256,
        "review_sha256": sha256_file(review) if review is not None else None,
        "canonical_modes": list[JsonValue](modes),
        "unreviewed_reference_failures": unreviewed,
        "cells": _cells(
            runs, matches, budget=design.budget, n_modes=len(modes) if not unreviewed else 0
        ),
    }
