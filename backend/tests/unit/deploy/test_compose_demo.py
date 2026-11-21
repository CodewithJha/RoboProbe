"""Static checks for the T-047 compose services and the demo campaign file."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from roboprobe.scenario._documents import load_yaml_document, read_document, validate_document

pytestmark = pytest.mark.unit

_REPO = Path(__file__).resolve().parents[4]


def test_compose_smoke_script_accepts_the_core_file() -> None:
    script = _REPO / "scripts" / "compose_smoke.sh"
    completed = subprocess.run(  # noqa: S603 - fixed bash and repository script
        ["bash", str(script)],  # noqa: S607 - bash is a fixed executable name
        cwd=_REPO,
        capture_output=True,
        text=True,
        check=False,
    )
    assert completed.returncode == 0, completed.stderr
    assert "compose file ok" in completed.stdout


def test_demo_campaign_matches_the_campaign_schema() -> None:
    path = _REPO / "configs" / "campaigns" / "k2d_demo_50.yaml"
    document = load_yaml_document(read_document(path), source=str(path))
    validate_document(document, schema="campaign", source=str(path))
    assert isinstance(document, dict)
    assert document["budget"] == 50
    strategy = document["strategy"]
    assert isinstance(strategy, dict)
    assert strategy["id"] == "S-PROBE"
    assert document["start"] is True
