"""Optional OpenTelemetry tracing (docs/21 §5.3, T-126).

``configure_tracing`` is a no-op unless ``observability.otlp_endpoint`` is set, and it imports
``opentelemetry`` only in that case (extra ``roboprobe[otel]``). Span names match docs/21 §5.3:
``campaign.tick``, ``strategy.propose``, ``run.execute``, ``materialize``, ``episode``, ``judge``,
``persist``.

Implements: T-126, NFR-OBS-001, NFR-OBS-002
"""

from __future__ import annotations

import importlib
from collections.abc import Iterator
from contextlib import contextmanager
from typing import Any

from roboprobe.core.logging import bind_context
from roboprobe.core.settings.observability import ObservabilitySettings

__all__ = [
    "configure_tracing",
    "current_trace_id",
    "instrument_fastapi",
    "instrument_sqlalchemy",
    "span",
]

class _TracingState:
    """Process-wide flag so a second configure call does not replace the provider."""

    configured: bool = False


_state = _TracingState()


def configure_tracing(
    settings: ObservabilitySettings,
    service_name: str,
    *,
    exporter: object | None = None,
) -> None:
    """Install a tracer provider, or return without importing OpenTelemetry.

    Args:
        settings: Observability section. Tracing stays off when ``otlp_endpoint`` is unset.
        service_name: Fallback ``service.name`` when ``settings.service_name`` is unset.
        exporter: Span exporter override (tests). Ignored when tracing is off.
    """
    if settings.otlp_endpoint is None or _state.configured:
        return
    trace_sdk = importlib.import_module("opentelemetry.sdk.trace")
    export_mod = importlib.import_module("opentelemetry.sdk.trace.export")
    resources = importlib.import_module("opentelemetry.sdk.resources")
    otel_trace = importlib.import_module("opentelemetry.trace")
    name = settings.service_name or service_name
    provider = trace_sdk.TracerProvider(resource=resources.Resource.create({"service.name": name}))
    if exporter is None:
        otlp = importlib.import_module("opentelemetry.exporter.otlp.proto.http.trace_exporter")
        sink = otlp.OTLPSpanExporter(endpoint=str(settings.otlp_endpoint))
        processor = export_mod.BatchSpanProcessor(sink)
    else:
        processor = export_mod.SimpleSpanProcessor(exporter)
    provider.add_span_processor(processor)
    otel_trace.set_tracer_provider(provider)
    _state.configured = True


def instrument_fastapi(app: object) -> None:
    """Attach the FastAPI instrumentor when tracing is on."""
    if not _state.configured:
        return
    module = importlib.import_module("opentelemetry.instrumentation.fastapi")
    module.FastAPIInstrumentor.instrument_app(app)


def instrument_sqlalchemy(engine: object) -> None:
    """Attach the SQLAlchemy instrumentor when tracing is on."""
    if not _state.configured:
        return
    module = importlib.import_module("opentelemetry.instrumentation.sqlalchemy")
    module.SQLAlchemyInstrumentor().instrument(engine=engine)


def current_trace_id() -> str | None:
    """Return the active span's trace id, or ``None`` when tracing is off or no span is current."""
    if not _state.configured:
        return None
    otel_trace = importlib.import_module("opentelemetry.trace")
    context = otel_trace.get_current_span().get_span_context()
    if not context.is_valid:
        return None
    return format(context.trace_id, "032x")


@contextmanager
def span(name: str, **attributes: str) -> Iterator[None]:
    """Record a span named ``name`` and bind its trace id onto the log context.

    A no-op (and no OpenTelemetry import) until :func:`configure_tracing` has enabled tracing.
    """
    if not _state.configured:
        yield
        return
    otel_trace = importlib.import_module("opentelemetry.trace")
    tracer: Any = otel_trace.get_tracer("roboprobe")
    with tracer.start_as_current_span(name) as current:
        for key, value in attributes.items():
            current.set_attribute(key, value)
        trace_id = current_trace_id()
        if trace_id is None:
            yield
            return
        with bind_context(trace_id=trace_id):
            yield
