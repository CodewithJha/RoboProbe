"""TM-05: user-provided labels are escaped in the HTML report (T-078b, T-109)."""

from __future__ import annotations

from pathlib import Path

import pytest

from roboprobe.reporting._env import template_env

pytestmark = pytest.mark.security

_TEMPLATE = (
    Path(__file__).resolve().parents[2]
    / "src/roboprobe/reporting/templates/campaign/report.html.j2"
)


def test_mode_label_is_escaped() -> None:
    source = _TEMPLATE.read_text(encoding="utf-8")
    assert "{{ mode.label }}" in source
    assert "mode.label | safe" not in source
    html = (
        template_env()
        .from_string("<h3>{{ mode.label }}</h3>")
        .render(mode={"label": "<script>alert(1)</script>"})
    )
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
