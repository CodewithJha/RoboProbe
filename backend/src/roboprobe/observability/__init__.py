"""Optional tracing helpers (docs/21 §5.3).

Layer: application support. OpenTelemetry is imported only after an OTLP endpoint is configured.
"""

from roboprobe.observability.tracing import (
    configure_tracing,
    current_trace_id,
    instrument_fastapi,
    instrument_sqlalchemy,
    span,
)

__all__ = [
    "configure_tracing",
    "current_trace_id",
    "instrument_fastapi",
    "instrument_sqlalchemy",
    "span",
]
