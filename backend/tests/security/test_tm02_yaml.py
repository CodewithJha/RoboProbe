"""TM-02: unsafe YAML tags, oversized bodies and alias bombs are rejected (T-109)."""

from __future__ import annotations

import pytest

from roboprobe.core.errors import ValidationError
from roboprobe.core.settings.scenario import ScenarioSettings
from roboprobe.scenario._documents import load_yaml_document

pytestmark = pytest.mark.security

_BOMB = """
a: &a ["x"]
b: &b [*a, *a, *a, *a, *a, *a, *a, *a, *a, *a, *a, *a, *a, *a, *a, *a, *a, *a, *a, *a]
c: [*b, *b, *b, *b, *b, *b, *b, *b, *b, *b, *b, *b, *b, *b, *b, *b, *b, *b, *b, *b]
"""


def test_python_tag_rejected() -> None:
    with pytest.raises(ValidationError):
        load_yaml_document("!!python/object:os.system [id]\n", source="<upload>")


def test_billion_laughs_aliases_rejected() -> None:
    limit = ScenarioSettings.model_fields["yaml_max_aliases"].default
    assert isinstance(limit, int)
    with pytest.raises(ValidationError, match="alias"):
        load_yaml_document(_BOMB, source="<upload>", max_aliases=limit)


def test_oversized_upload_rejected() -> None:
    with pytest.raises(ValidationError, match="bytes"):
        load_yaml_document("id: warehouse_v1\n", source="<upload>", max_bytes=8)
