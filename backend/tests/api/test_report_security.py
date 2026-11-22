"""Report HTML is served without script privileges (T-084a, TM-05)."""

from pathlib import Path
from types import SimpleNamespace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient

from roboprobe.bootstrap.api import build_api
from roboprobe.core.settings import RoboProbeSettings

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


def test_report_pool_honors_api_worker_limit(api_settings: RoboProbeSettings) -> None:
    report_workers = api_settings.runner.analysis.max_workers + 1
    settings = api_settings.model_copy(
        update={"api": api_settings.api.model_copy(update={"report_workers": report_workers})}
    )
    services = build_api(settings)
    try:
        assert services.report_jobs._executor._max_workers == report_workers
    finally:
        services.close()
