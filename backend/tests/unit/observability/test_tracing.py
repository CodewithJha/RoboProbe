"""Tracing stays off unless an OTLP endpoint is configured (T-126, docs/21 §5.3)."""

from __future__ import annotations

import subprocess
import sys

import pytest

from roboprobe.core.settings.observability import ObservabilitySettings
from roboprobe.observability import tracing

pytestmark = pytest.mark.unit

_SPAN_NAMES = (
    "campaign.tick",
    "strategy.propose",
    "run.execute",
    "materialize",
    "episode",
    "judge",
    "persist",
)


def test_disabled_tracing_does_not_import_opentelemetry() -> None:
    code = (
        "import sys\n"
        "from roboprobe.core.settings.observability import ObservabilitySettings\n"
        "from roboprobe.observability import tracing\n"
        "tracing.configure_tracing(ObservabilitySettings(), 'roboprobe-api')\n"
        "cm = tracing.span('campaign.tick')\n"
        "cm.__enter__()\n"
        "assert tracing.current_trace_id() is None\n"
        "cm.__exit__(None, None, None)\n"
        "assert not any(name.startswith('opentelemetry') for name in sys.modules)\n"
    )
    subprocess.run([sys.executable, "-c", code], check=True)  # noqa: S603


def test_enabled_tracing_records_documented_span_names() -> None:
    pytest.importorskip("opentelemetry")
    from opentelemetry.sdk.trace.export.in_memory_span_exporter import (  # noqa: PLC0415
        InMemorySpanExporter,
    )

    exporter = InMemorySpanExporter()
    tracing._state.configured = False
    tracing.configure_tracing(
        ObservabilitySettings(otlp_endpoint="http://127.0.0.1:4318/v1/traces"),
        "roboprobe-test",
        exporter=exporter,
    )
    with tracing.span("run.execute"):
        with tracing.span("materialize"):
            pass
        with tracing.span("episode"):
            pass
        with tracing.span("judge"):
            pass
        with tracing.span("persist"):
            pass
    with tracing.span("campaign.tick"), tracing.span("strategy.propose"):
        assert tracing.current_trace_id() is not None
    names = {span.name for span in exporter.get_finished_spans()}
    assert names == set(_SPAN_NAMES)
