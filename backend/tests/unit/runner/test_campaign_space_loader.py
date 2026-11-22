"""Uploaded space versions and pins survive execution restore (T-081b)."""

from pathlib import Path
from types import SimpleNamespace

import pytest
import yaml
from tests.fakes.store import InMemoryUnitOfWork

from roboprobe.runner.space_loader import load_campaign_space
from roboprobe.scenario.space import ScenarioSpace
from roboprobe.store.records import SpaceRecord

pytestmark = pytest.mark.unit
ROOT = Path(__file__).resolve().parents[4]


def test_uploaded_space_uses_stored_definition_and_pins() -> None:
    document = yaml.safe_load((ROOT / "configs/scenario_spaces/warehouse_v1.yaml").read_text())
    document["id"] = "uploaded_custom_space"
    space = ScenarioSpace.from_text(yaml.safe_dump(document), source="test", base_dir=ROOT)
    assert not (ROOT / "configs/scenario_spaces/uploaded_custom_space.yaml").exists()
    parameter = space.params[0]
    campaign = SimpleNamespace(
        space_id=space.id, space_version=space.version, pins={parameter.id: parameter.nominal}
    )
    with InMemoryUnitOfWork() as uow:
        uow.spaces.add(
            SpaceRecord(id=space.id, version=space.version, name=space.name, definition=document)
        )
        restored = load_campaign_space(uow, campaign, root=ROOT)
    assert restored.id == space.id
    assert restored.version == space.version
    assert restored.dim == space.dim - 1
    assert restored.pins == campaign.pins
