#!/usr/bin/env python3
"""Export T-107 fixtures from a running, seeded RoboProbe API.

Verify each response against the committed OpenAPI snapshot before writing any JSON.
Use ROBOPROBE_API__TOKEN (or ROBOPROBE_API_TOKEN) for a protected API.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from http import HTTPStatus
from pathlib import Path
from typing import Any
from urllib.parse import urlsplit
from uuid import UUID

import httpx2
from jsonschema import Draft202012Validator, FormatChecker, ValidationError

_REPO = Path(__file__).resolve().parents[1]
_DEFAULT_OUTPUT = _REPO / "web" / "src" / "test" / "fixtures"
_OPENAPI = _REPO / "api" / "openapi.json"

_CAMPAIGNS = "/api/v1/campaigns"
_CAMPAIGN = _CAMPAIGNS + "/{campaign_id}"


def _base_url(value: str) -> str:
    try:
        parsed = urlsplit(value)
    except ValueError as exc:
        msg = "base URL must be a valid HTTP or HTTPS server URL"
        raise argparse.ArgumentTypeError(msg) from exc
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
        or parsed.query
        or parsed.fragment
    ):
        msg = (
            "base URL must be HTTP or HTTPS without credentials, a query, or a fragment"
        )
        raise argparse.ArgumentTypeError(msg)
    return value.rstrip("/")


def _positive_int(value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        msg = "expected a positive integer"
        raise argparse.ArgumentTypeError(msg) from exc
    if parsed < 1:
        msg = "expected a positive integer"
        raise argparse.ArgumentTypeError(msg)
    return parsed


def _fetch(
    client: httpx2.Client,
    spec: dict[str, Any],
    route: str,
    ids: dict[str, UUID],
    params: dict[str, str | int],
) -> str:
    try:
        response = client.get(route.format_map(ids), params=params)
    except httpx2.HTTPError as exc:
        msg = f"could not fetch {route}: {type(exc).__name__}"
        raise ValueError(msg) from exc
    if response.status_code != HTTPStatus.OK:
        msg = f"GET {route} returned HTTP {response.status_code}; expected 200"
        raise ValueError(msg)

    try:
        response_schema = spec["paths"][route]["get"]["responses"]["200"]["content"][
            "application/json"
        ]["schema"]
    except KeyError as exc:
        msg = f"missing JSON response schema for GET {route}"
        raise ValueError(msg) from exc
    validator = Draft202012Validator(
        {**response_schema, "components": spec["components"]},
        format_checker=FormatChecker(),
    )
    try:
        payload = response.json()
        validator.validate(payload)
        return (
            json.dumps(
                payload, ensure_ascii=False, indent=2, sort_keys=True, allow_nan=False
            )
            + "\n"
        )
    except ValidationError as exc:
        msg = f"GET {route} failed OpenAPI validation at {exc.json_path} ({exc.validator})"
        raise ValueError(msg) from exc
    except ValueError as exc:
        msg = f"GET {route} did not return valid JSON"
        raise ValueError(msg) from exc


def main(argv: list[str] | None = None) -> int:
    """Run the fixture exporter and return a shell status code."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--base-url", required=True, type=_base_url, help="API server URL"
    )
    parser.add_argument("--campaign-id", required=True, type=UUID)
    parser.add_argument("--run-id", required=True, type=UUID)
    parser.add_argument("--experiment-id", required=True, type=UUID)
    parser.add_argument("--risk-x", default="robot.max_speed")
    parser.add_argument("--risk-y", default="obstacle.clearance")
    parser.add_argument(
        "--risk-resolution",
        required=True,
        type=_positive_int,
        help="Stored slice resolution",
    )
    parser.add_argument(
        "--runs-limit", type=_positive_int, help="Page size for the runs fixture"
    )
    parser.add_argument(
        "--output", type=Path, default=_DEFAULT_OUTPUT, help="Output directory"
    )
    args = parser.parse_args(argv)

    ids = {
        "campaign_id": args.campaign_id,
        "run_id": args.run_id,
        "experiment_id": args.experiment_id,
    }
    runs_query = {} if args.runs_limit is None else {"limit": args.runs_limit}
    risk_query = {
        "x": args.risk_x,
        "y": args.risk_y,
        "resolution": args.risk_resolution,
    }
    requests: tuple[tuple[str, str, dict[str, str | int]], ...] = (
        ("campaigns", _CAMPAIGNS, {}),
        ("runs_page", f"{_CAMPAIGN}/runs", runs_query),
        ("run_detail", "/api/v1/runs/{run_id}", {}),
        ("modes", f"{_CAMPAIGN}/modes", {}),
        ("importance", f"{_CAMPAIGN}/importance", {}),
        ("risk_slice", f"{_CAMPAIGN}/risk/slice", risk_query),
        ("comparison", "/api/v1/experiments/{experiment_id}/comparison", {}),
    )
    token = os.environ.get("ROBOPROBE_API__TOKEN") or os.environ.get(
        "ROBOPROBE_API_TOKEN"
    )
    headers = {"Accept": "application/json"}
    if token:
        headers["Authorization"] = f"Bearer {token}"

    try:
        spec = json.loads(_OPENAPI.read_text(encoding="utf-8"))
        with httpx2.Client(
            base_url=args.base_url,
            headers=headers,
            follow_redirects=False,
            trust_env=False,
        ) as client:
            fixtures = {
                name: _fetch(client, spec, route, ids, params)
                for name, route, params in requests
            }
        args.output.mkdir(parents=True, exist_ok=True)
        for name, contents in fixtures.items():
            (args.output / f"{name}.json").write_text(
                contents, encoding="utf-8", newline="\n"
            )
    except httpx2.InvalidURL:
        print("Invalid API server URL", file=sys.stderr)
        return 1
    except (OSError, ValueError) as exc:
        print(exc, file=sys.stderr)
        return 1
    print(f"Exported {len(fixtures)} API fixtures to {args.output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
