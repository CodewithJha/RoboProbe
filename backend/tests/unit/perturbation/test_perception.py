"""Tests for illumination-dependent depth degradation (T-031b; docs/06 §3.3)."""

from __future__ import annotations

import dataclasses
import math
from pathlib import Path
from typing import Any

import numpy as np
import pytest
import yaml

from roboprobe.core.seeding import PERCEPTION, RUN, make_rng
from roboprobe.core.settings import BackendsSettings
from roboprobe.perturbation.perception import PerceptionModel

pytestmark = pytest.mark.unit

REPO_ROOT = Path(__file__).resolve().parents[4]
MODEL_FILE = REPO_ROOT / "configs" / "perception" / "oakd_lowlight_v1.yaml"
N_RAYS = 100_000
SIGMA_BOUND = 4.0

# docs/06 §3.3 constants, restated independently of the YAML file.
L_REF, L_MIN = 300.0, 5.0


def doc_eta(lux: float) -> float:
    return min(1.0, max(0.0, math.log10(L_REF / lux) / math.log10(L_REF / L_MIN)))


def doc_p_valid(eta: float) -> float:
    return 1 - 0.85 * eta**2


def doc_sigma(r: float, eta: float) -> float:
    return 0.005 + 0.01 * r**2 * (1 + 4 * eta)


def doc_r_max(eta: float) -> float:
    return 3.0 * (1 - 0.6 * eta)


@pytest.fixture(scope="module")
def model() -> PerceptionModel:
    return PerceptionModel.from_yaml(MODEL_FILE)


def rng(seed: int = 7) -> np.random.Generator:
    return make_rng(seed, RUN, 0, PERCEPTION)


def test_shipped_file_is_the_settings_default(model: PerceptionModel) -> None:
    default = BackendsSettings().gazebo_nav2.perception_model_file
    assert REPO_ROOT / default == MODEL_FILE
    assert model.id == "oakd_lowlight_v1"


@pytest.mark.parametrize(("lux", "eta"), [(5.0, 1.0), (300.0, 0.0), (1000.0, 0.0), (1.0, 1.0)])
def test_eta_end_points(model: PerceptionModel, lux: float, eta: float) -> None:
    assert model.eta(lux) == eta


@pytest.mark.parametrize("lux", [5.0, 32.0, 300.0, 1000.0])
def test_formulas_match_doc(model: PerceptionModel, lux: float) -> None:
    eta = doc_eta(lux)
    assert model.eta(lux) == pytest.approx(eta)
    assert model.p_valid(eta) == pytest.approx(doc_p_valid(eta))
    assert model.r_max(eta) == pytest.approx(doc_r_max(eta))
    ranges = np.array([0.5, 1.0, 2.0])
    np.testing.assert_allclose(model.sigma_d(ranges, eta), [doc_sigma(r, eta) for r in ranges])


def test_32_lux_reference_values(model: PerceptionModel) -> None:
    eta = model.eta(32.0)
    assert eta == pytest.approx(0.5466, abs=1e-4)
    assert model.p_valid(eta) == pytest.approx(0.7460, abs=1e-4)
    assert model.r_max(eta) == pytest.approx(2.0161, abs=1e-4)


def test_degrade_matches_formula_draw_by_draw(model: PerceptionModel) -> None:
    ranges = np.array([0.5, 1.0, 1.5, 2.5, np.inf])
    lux = 32.0
    eta = doc_eta(lux)
    ref = rng()
    z = ref.standard_normal(ranges.shape)
    u = ref.random(ranges.shape)
    out = model.degrade(ranges, lux, rng())
    for i, r in enumerate(ranges[:-1]):
        lost = r > doc_r_max(eta) or u[i] >= doc_p_valid(eta)
        expected = math.inf if lost else max(r + doc_sigma(r, eta) * z[i], 0.0)
        assert out[i] == pytest.approx(expected)
    assert out[-1] == np.inf


def test_valid_fraction_within_binomial_ci(model: PerceptionModel) -> None:
    lux = 32.0
    p = doc_p_valid(doc_eta(lux))
    out = model.degrade(np.full(N_RAYS, 1.0), lux, rng())
    valid = np.isfinite(out).mean()
    assert abs(valid - p) < SIGMA_BOUND * math.sqrt(p * (1 - p) / N_RAYS)


def test_noise_std_matches_sigma_d(model: PerceptionModel) -> None:
    r, lux = 2.0, 1000.0
    out = model.degrade(np.full(N_RAYS, r), lux, rng())
    assert np.isfinite(out).all()  # bright: p_valid = 1, r < r_max
    assert out.std() == pytest.approx(doc_sigma(r, 0.0), rel=0.02)


def test_beyond_effective_range_is_lost(model: PerceptionModel) -> None:
    out = model.degrade(np.array([2.9, 3.1]), 1000.0, rng())
    assert np.isfinite(out[0])
    assert out[1] == np.inf
    assert model.degrade(np.array([2.5]), 5.0, rng())[0] == np.inf  # r_max = 1.2 m when dark


def test_noise_never_goes_negative(model: PerceptionModel) -> None:
    out = model.degrade(np.full(N_RAYS, 0.001), 300.0, rng())
    assert out.min() >= 0.0


def test_same_seed_identical_and_input_untouched(model: PerceptionModel) -> None:
    ranges = np.linspace(0.2, 3.5, 60)
    before = ranges.copy()
    first = model.degrade(ranges, 20.0, rng())
    np.testing.assert_array_equal(first, model.degrade(ranges, 20.0, rng()))
    np.testing.assert_array_equal(ranges, before)
    assert first.dtype == np.float64


def test_stream_use_is_parameter_independent(model: PerceptionModel) -> None:
    ranges = np.ones(10)
    bright, dark = rng(), rng()
    model.degrade(ranges, 1000.0, bright)
    model.degrade(ranges, 5.0, dark)
    assert bright.random() == dark.random()


@pytest.mark.parametrize("lux", [0.0, -1.0, math.nan, math.inf])
def test_invalid_illuminance(model: PerceptionModel, lux: float) -> None:
    with pytest.raises(ValueError, match="illuminance"):
        model.eta(lux)


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("l_min_lux", 0.0),
        ("l_min_lux", 400.0),
        ("valid_loss", 1.5),
        ("sigma_base_m", -0.1),
        ("r_max_bright_m", 0.0),
        ("r_max_dark_reduction", 1.0),
        ("sigma_r2_per_m", math.nan),
        ("id", ""),
    ],
)
def test_invalid_constants(model: PerceptionModel, field: str, value: Any) -> None:
    with pytest.raises(ValueError, match="invalid perception model"):
        dataclasses.replace(model, **{field: value})


def write_model(tmp_path: Path, document: object) -> Path:
    path = tmp_path / "model.yaml"
    path.write_text(yaml.safe_dump(document), encoding="utf-8")
    return path


def base_document() -> dict[str, Any]:
    document: dict[str, Any] = yaml.safe_load(MODEL_FILE.read_text(encoding="utf-8"))
    return document


def test_integer_constants_are_accepted(tmp_path: Path) -> None:
    document = base_document()
    document["constants"]["l_ref_lux"] = 300
    assert PerceptionModel.from_yaml(write_model(tmp_path, document)).l_ref_lux == L_REF


@pytest.mark.parametrize(
    ("mutate", "match"),
    [
        (lambda d: d.update(schema_version=2), "schema_version"),
        (lambda d: d["constants"].pop("valid_loss"), "exactly"),
        (lambda d: d["constants"].update(extra=1.0), "exactly"),
        (lambda d: d.update(constants=[1, 2]), "exactly"),
        (lambda d: d["constants"].update(valid_loss="high"), "non-numeric"),
        (lambda d: d["constants"].update(valid_loss=True), "non-numeric"),
    ],
)
def test_invalid_files(tmp_path: Path, mutate: Any, match: str) -> None:
    document = base_document()
    mutate(document)
    with pytest.raises(ValueError, match=match):
        PerceptionModel.from_yaml(write_model(tmp_path, document))


def test_non_mapping_file(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="schema_version"):
        PerceptionModel.from_yaml(write_model(tmp_path, [1, 2]))
