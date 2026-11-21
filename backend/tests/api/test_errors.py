"""RFC 9457 problem+json envelope (T-080b)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from roboprobe.api.app import create_app
from roboprobe.api.errors import _field_error, problem_type_url
from roboprobe.core.errors import (
    API_ERROR_CODES,
    ConflictError,
    ErrorCode,
    NotFoundError,
    ValidationError,
)
from roboprobe.core.settings import RoboProbeSettings

pytestmark = pytest.mark.unit

DOCS = Path(__file__).resolve().parents[3] / "docs" / "errors.md"


@pytest.fixture
def error_client(api_settings: RoboProbeSettings) -> TestClient:
    app = create_app(api_settings)
    app.state.readiness_failures = []

    @app.get("/api/v1/_boom/{code}")
    def boom(code: str) -> None:
        mapping: dict[str, Exception] = {
            "VALIDATION_ERROR": ValidationError("bad field", context={"field": "budget"}),
            "NOT_FOUND": NotFoundError("missing"),
            "CAMPAIGN_INVALID_TRANSITION": ConflictError(
                "cannot pause", code=ErrorCode.CAMPAIGN_INVALID_TRANSITION
            ),
            "SPACE_INVALID": ValidationError("space", code=ErrorCode.SPACE_INVALID),
            "BACKEND_UNSUPPORTED_PARAM": ValidationError(
                "param", code=ErrorCode.BACKEND_UNSUPPORTED_PARAM
            ),
            "NO_WORKERS": ConflictError("none", code=ErrorCode.NO_WORKERS),
            "PRECONDITION_FAILED": ValidationError("etag", code=ErrorCode.PRECONDITION_FAILED),
            "UNAUTHORIZED": ConflictError("nope", code=ErrorCode.UNAUTHORIZED),
            "INTERNAL": RuntimeError("secret stack"),
        }
        raise mapping[code]

    @app.post("/api/v1/_validate")
    def validate(body: dict[str, dict[str, float]]) -> dict[str, str]:
        return {"ok": "1"}

    return TestClient(app, raise_server_exceptions=False)


@pytest.mark.parametrize("code", sorted(c.value for c in API_ERROR_CODES))
def test_each_api_error_code(error_client: TestClient, code: str) -> None:
    response = error_client.get(f"/api/v1/_boom/{code}")
    body = response.json()
    assert body["code"] == code
    assert response.headers["content-type"].startswith("application/problem+json")
    assert "traceback" not in response.text.lower()
    assert "secret stack" not in response.text
    expected_status = {
        "VALIDATION_ERROR": 422,
        "NOT_FOUND": 404,
        "CAMPAIGN_INVALID_TRANSITION": 409,
        "SPACE_INVALID": 422,
        "BACKEND_UNSUPPORTED_PARAM": 422,
        "NO_WORKERS": 409,
        "PRECONDITION_FAILED": 412,
        "UNAUTHORIZED": 401,
        "INTERNAL": 500,
    }[code]
    assert response.status_code == expected_status
    assert body["status"] == expected_status
    if code == "INTERNAL":
        assert body.get("trace_id")


def test_validation_pointer_nested() -> None:
    """RFC 6901 pointers include nested paths such as ``/strategy/params/epsilon``."""
    err = {
        "type": "float_parsing",
        "loc": ("body", "strategy", "params", "epsilon"),
        "msg": "Input should be a valid number",
        "input": "nope",
    }
    assert _field_error(err).pointer == "/strategy/params/epsilon"


def test_docs_anchors_match_type_urls(api_settings: RoboProbeSettings) -> None:
    text = DOCS.read_text()
    headings = set(re.findall(r"^## ([a-z0-9-]+)$", text, flags=re.M))
    for code in API_ERROR_CODES:
        url = problem_type_url(api_settings.api.error_type_base, code)
        slug = url.rsplit("#", 1)[-1]
        assert slug in headings
