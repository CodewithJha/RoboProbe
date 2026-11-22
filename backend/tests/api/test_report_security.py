"""Report HTML is served without script privileges (T-084a, TM-05)."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

pytestmark = pytest.mark.unit


def test_report_content_has_csp_and_nosniff(api_client: TestClient, tmp_path: Path) -> None:
    html = tmp_path / "report.html"
    html.write_text("<html><body>Report</body></html>")
    job = SimpleNamespace(html_path=html, status="COMPLETED", kind="campaign")
    api_client.app.state.services.report_jobs = SimpleNamespace(get=lambda _: job)
    response = api_client.get(f"/api/v1/reports/{uuid4()}/content")
    assert response.status_code == 200
    assert "default-src 'none'" in response.headers["content-security-policy"]
    assert response.headers["x-content-type-options"] == "nosniff"
