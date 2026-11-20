"""Composition roots: the only place that wires concrete adapters to application services.

Factories: :func:`build_worker`, :func:`build_orchestrator`, :func:`build_cli_services`,
:func:`build_api` (stub until T-080a). See docs/34 §3 and ADR-0016.

Layer: Application (L3) — composition roots. See docs/16 §2 for the allowed import directions.

Implements: T-046, NFR-EXT-001, NFR-EXT-002, PR-19
"""

from roboprobe.bootstrap.api import ApiServices, build_api, build_api_infra
from roboprobe.bootstrap.cli import CliServices, build_cli_services
from roboprobe.bootstrap.orchestrator import OrchestratorServices, build_orchestrator
from roboprobe.bootstrap.worker import build_worker

__all__ = [
    "ApiServices",
    "CliServices",
    "OrchestratorServices",
    "build_api",
    "build_api_infra",
    "build_cli_services",
    "build_orchestrator",
    "build_worker",
]
