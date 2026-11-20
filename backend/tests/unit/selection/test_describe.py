"""Strategy describe / params validation (T-060)."""

from __future__ import annotations

import pytest

from roboprobe.core import errors
from roboprobe.selection.meta import strategies_payload
from roboprobe.selection.registry import available, describe, validate_params

pytestmark = pytest.mark.unit


def test_describe_covers_every_registered_strategy() -> None:
    infos = describe()
    ids = {info.id for info in infos}
    assert ids == set(available())
    for info in infos:
        assert info.description
        assert "properties" in info.params_schema or info.params_schema.get("type") == "object"
        assert info.family in {"baseline", "learning", "plugin"}


def test_probe_description_matches_wizard_tone() -> None:
    probe = next(info for info in describe() if info.id == "S-PROBE")
    assert "failures" in probe.description.lower()


def test_invalid_params_raise_validation_error_with_field_path() -> None:
    with pytest.raises(errors.ValidationError) as excinfo:
        validate_params("S-PROBE", {"epsilon": 2.0})
    assert excinfo.value.code == errors.ErrorCode.VALIDATION_ERROR
    assert "field" in excinfo.value.context
    assert "epsilon" in str(excinfo.value.context["field"])


def test_meta_hook_payload_is_json_ready() -> None:
    payload = strategies_payload()
    assert isinstance(payload, list)
    assert {row["id"] for row in payload} == set(available())
