"""kinematic2d model file (T-029; docs/10 §7.1)."""

from __future__ import annotations

from pathlib import Path

import pytest
import yaml

from roboprobe.backends.kinematic2d.model import Kinematic2DModel
from roboprobe.core import errors

pytestmark = pytest.mark.unit

REPO = Path(__file__).resolve().parents[5]
MODEL = REPO / "configs" / "backends" / "kinematic2d_v1.yaml"


def test_shipped_model_has_doc_10_constants() -> None:
    model = Kinematic2DModel.from_yaml(MODEL)
    assert model.id == "kinematic2d_v1"
    assert model.robot.footprint_radius_m == 0.17
    assert model.robot.a_max_mps2 == 0.5
    assert model.robot.alpha_max_radps2 == 2.0
    assert model.costmap.inflation_m == 0.3
    assert model.controller.lookahead_m == 0.45
    assert model.friction.mu_base == 0.32
    assert model.planner.replan_hz == 1.0
    assert model.world.start_x_m == 2.12
    assert model.world.start_y_m == -21.3


def test_invalid_values_rejected(tmp_path: Path) -> None:
    document = yaml.safe_load(MODEL.read_text(encoding="utf-8"))
    document["robot"]["a_max_mps2"] = 0
    path = tmp_path / "bad.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    with pytest.raises(errors.ValidationError):
        Kinematic2DModel.from_yaml(path)
