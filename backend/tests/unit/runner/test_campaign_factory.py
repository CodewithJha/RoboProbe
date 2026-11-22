"""Shared campaign checks and reproducible snapshots (T-081b, FR-API-001)."""

from pathlib import Path

import pytest

from roboprobe.core.errors import ValidationError
from roboprobe.core.settings import RoboProbeSettings
from roboprobe.runner.campaign_factory import CampaignFactory
from roboprobe.runner.campaign_spec import CampaignCreate
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.selection.base import StrategyContext
from roboprobe.selection.registry import create

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[4]


@pytest.fixture
def space() -> ScenarioSpace:
    return ScenarioSpace.from_yaml(
        ROOT / "configs/scenario_spaces/warehouse_v1.yaml", base_dir=ROOT
    )


def request(**overrides: object) -> CampaignCreate:
    return CampaignCreate.model_validate(
        {
            "space": {"id": "warehouse_v1"},
            "backend": "kinematic2d",
            "strategy": {"id": "S-RANDOM", "seed": 42},
            "budget": 5,
            **overrides,
        }
    )


def prepare(space: ScenarioSpace, **overrides: object) -> CampaignCreate:
    return CampaignFactory(RoboProbeSettings()).prepare(
        request(**overrides), space=space, supported_params=frozenset(p.id for p in space.params)
    )


def test_oracle_snapshot_is_complete_and_merged(space: ScenarioSpace) -> None:
    result = prepare(space, oracle_overrides={"clear": {"d_safe": 0.2}})
    assert result.oracle_overrides["clear"]["d_safe"] == 0.2
    assert "infra" in result.oracle_overrides
    assert "allow_repeats" in result.strategy.params


@pytest.mark.parametrize(
    "override",
    [
        {"budget": 10**12},
        {"batch_size": 10**12},
        {"pins": {"unknown": 1}},
        {"oracle_overrides": {"loc": {"e_max": -1}}},
        {"strategy": {"id": "unknown"}},
        {"strategy": {"id": "S-RANDOM", "params": {"unknown": 1}}},
    ],
)
def test_invalid_campaign_is_rejected(space: ScenarioSpace, override: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        prepare(space, **override)


def test_unsupported_free_parameters_are_rejected(space: ScenarioSpace) -> None:
    with pytest.raises(ValidationError) as caught:
        CampaignFactory(RoboProbeSettings()).prepare(
            request(), space=space, supported_params=frozenset()
        )
    assert caught.value.code.value == "BACKEND_UNSUPPORTED_PARAM"


def test_pinned_parameter_need_not_be_supported(space: ScenarioSpace) -> None:
    parameter = space.params[0]
    CampaignFactory(RoboProbeSettings()).prepare(
        request(pins={parameter.id: parameter.nominal}),
        space=space,
        supported_params=frozenset(p.id for p in space.params if p.id != parameter.id),
    )


def test_selection_defaults_are_complete_and_restored(space: ScenarioSpace) -> None:

    settings = RoboProbeSettings(
        selection={"probe": {"epsilon": 0.2}, "gp": {"max_points": 47}, "acq": {"num_restarts": 3}},
        scenario={"constraint_max_attempts": 23},
    )
    prepared = CampaignFactory(settings).prepare(
        request(strategy={"id": "S-PROBE", "params": {"epsilon": 0.4}}),
        space=space,
        supported_params=frozenset(p.id for p in space.params),
    )
    params = prepared.strategy.params
    assert params["epsilon"] == 0.4
    assert params["lambda_div"] == settings.selection.probe.lambda_div
    assert params["max_attempts"] == 23
    strategy = create(
        "S-PROBE", StrategyContext(space=space, budget=10, seed=42, batch_size=1, params=params)
    )
    assert strategy.ctx.selection.gp.max_points == 47
    assert strategy.ctx.selection.acq.num_restarts == 3
    assert strategy.ctx.scenario.constraint_max_attempts == 23
    assert "_resolved_settings" not in strategy.ctx.params
