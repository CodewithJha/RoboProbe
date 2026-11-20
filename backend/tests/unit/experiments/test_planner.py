"""Unit tests for experiment planner (T-102a; docs/14 §8, docs/33 §6)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from roboprobe.core import errors
from roboprobe.core.seeding import REP, derive_seed
from roboprobe.experiments.planner import (
    CampaignSpec,
    ComparabilityKey,
    ExperimentDesign,
    check_comparable,
    load_design,
    plan,
)

pytestmark = pytest.mark.unit

ROOT = 20261119
DEFAULT_SEEDS = 30
KEY = ComparabilityKey(
    space_version="abcdef123456",
    oracle_set_version="oracles-1",
    sut_config_hash="suthash00112233",
    backend_version="0.0.1",
    k2d_model_version="k2d-v1",
)


def _design(**overrides: object) -> ExperimentDesign:
    raw: dict[str, object] = {
        "schema_version": 1,
        "id": "exp02_analytic",
        "name": "analytic sanity",
        "backend": "benchmark",
        "space": {"id": "multi_mode_6d", "version": KEY.space_version},
        "sut_profile_id": "bench_default",
        "strategies": [
            {"id": "S-RANDOM"},
            {"id": "S-PROBE", "label": "PROBE-nodiv", "params": {"lambda_div": 0}},
        ],
        "seeds": {"root": ROOT, "count": 3},
        "budget": 30,
        "metrics": ["MET-01", "MET-03"],
    }
    raw.update(overrides)
    return ExperimentDesign.model_validate(raw)


def test_plan_is_deterministic_and_uses_crn_seeds() -> None:
    design = _design()
    first = plan(design, default_seeds=DEFAULT_SEEDS, key=KEY)
    second = plan(design, default_seeds=DEFAULT_SEEDS, key=KEY)
    assert first == second
    assert len(first) == 6  # 2 strategies x 3 seeds
    by_rep: dict[int, list[CampaignSpec]] = {}
    for spec in first:
        by_rep.setdefault(spec.experiment_rep, []).append(spec)
        assert spec.seed == derive_seed(ROOT, REP, spec.experiment_rep)
        assert spec.comparability == KEY
        assert spec.budget == 30
        assert spec.space_id == "multi_mode_6d"
    for rep, specs in by_rep.items():
        assert len(specs) == 2
        assert specs[0].seed == specs[1].seed == derive_seed(ROOT, REP, rep)
    labels = {(s.strategy_id, s.strategy_label) for s in first}
    assert labels == {("S-RANDOM", "S-RANDOM"), ("S-PROBE", "PROBE-nodiv")}
    nodiv = next(s for s in first if s.strategy_label == "PROBE-nodiv")
    assert nodiv.strategy_params == {"lambda_div": 0}


def test_plan_defaults_seed_count_from_settings() -> None:
    design = _design(seeds={"root": ROOT})
    specs = plan(design, default_seeds=4, key=KEY)
    assert len(specs) == 8
    assert {s.experiment_rep for s in specs} == {0, 1, 2, 3}


def test_mismatched_comparability_rejected() -> None:
    other = KEY.model_copy(update={"space_version": "ffffffffffff"})
    with pytest.raises(errors.ValidationError, match="comparability") as exc:
        check_comparable(KEY, other)
    assert "space_version" in str(exc.value.context)


def test_plan_rejects_space_version_mismatch_in_design() -> None:
    design = _design(space={"id": "multi_mode_6d", "version": "ffffffffffff"})
    with pytest.raises(errors.ValidationError, match=r"space\.version"):
        plan(design, default_seeds=DEFAULT_SEEDS, key=KEY)


def test_load_design_from_yaml(tmp_path: Path) -> None:
    path = tmp_path / "exp.yaml"
    path.write_text(
        yaml.safe_dump(
            {
                "schema_version": 1,
                "id": "exp_tiny",
                "backend": "kinematic2d",
                "space": {"id": "warehouse_v1"},
                "strategies": [{"id": "S-RANDOM"}, {"id": "S-LHS"}],
                "seeds": {"root": 1, "count": 2},
                "budget": 10,
            }
        ),
        encoding="utf-8",
    )
    design = load_design(path)
    assert design.id == "exp_tiny"
    specs = plan(design, default_seeds=DEFAULT_SEEDS, key=KEY)
    assert len(specs) == 4
