"""Structured logging: structlog configuration, context binding and secret redaction.

Layer: Kernel (L1). Every process calls :func:`configure_logging` once at start-up (from its
composition root); modules log with ``structlog.get_logger(__name__)`` using an event name from
:data:`EVENTS` plus key-values, never interpolated strings (docs/34 §6).

Implements: docs/34 §6, docs/21 §5.1, NFR-OBS-001.
"""

from __future__ import annotations

import logging
import re
import sys
from collections.abc import Iterator, Mapping, MutableMapping
from contextlib import contextmanager
from typing import Any, TextIO

import structlog
from structlog.typing import EventDict, Processor, WrappedLogger

from roboprobe.core.settings.observability import LoggingSettings

__all__ = [
    "CONTEXT_KEYS",
    "EVENTS",
    "REDACTED",
    "bind_context",
    "configure_logging",
    "redact_secrets",
]

EVENTS: frozenset[str] = frozenset(
    {
        "campaign.state_changed",
        "campaign.tick",
        "strategy.proposed",
        "selector.fallback",
        "run.claimed",
        "run.started",
        "run.finished",
        "run.lost",
        "run.execute_error",
        "run.requeued",
        "episode.launch_failed",
        "episode.teardown_orphans",
        "analysis.finished",
        "analysis.skipped",
        "analysis.failed",
        "analysis.artefact_write_failed",
        "api.request",
        "artifact.path_rejected",
        "sse.cursor_unavailable",
        "sse.listen_lost",
        "sse.poll_failed",
        "config.loaded",
        "scenario.unit_clipped",
        "orchestrator.campaign_started",
        "orchestrator.campaign_failed",
        "orchestrator.fail_status_error",
    }
)
"""Event catalogue (docs/34 §6). Extend, never rename; a test fails on unknown event names."""

CONTEXT_KEYS: frozenset[str] = frozenset(
    {"campaign_id", "run_id", "worker_id", "experiment_id", "trace_id"}
)
"""Identifiers that may be bound to every log line of the current context."""

REDACTED = "**********"
"""Replacement for redacted values (same mask as pydantic ``SecretStr``)."""

_SENSITIVE_KEY = re.compile(r"token|password|secret|dsn|authorization", re.IGNORECASE)


def redact_secrets(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
    """Mask the value of every key that looks sensitive, recursively (structlog processor).

    Args:
        _logger: Wrapped logger (unused).
        _method: Log method name (unused).
        event_dict: Event being processed.

    Returns:
        The event with sensitive values replaced by :data:`REDACTED`.
    """
    return _redact(event_dict)


def _redact[M: MutableMapping[str, Any]](mapping: M) -> M:
    for key, value in mapping.items():
        mapping[key] = REDACTED if _SENSITIVE_KEY.search(str(key)) else _redact_value(value)
    return mapping


def _redact_value(value: object) -> object:
    if isinstance(value, Mapping):
        return _redact(dict(value))
    if isinstance(value, list | tuple):
        return type(value)(_redact_value(item) for item in value)
    return value


class _NamedWriteLogger(structlog.WriteLogger):
    """``WriteLogger`` that remembers its name so ``add_logger_name`` can report it."""

    def __init__(self, file: TextIO, name: str) -> None:
        super().__init__(file)
        self.name = name


class _LoggerFactory:
    def __init__(self, stream: TextIO, default_name: str) -> None:
        self._stream = stream
        self._default_name = default_name

    def __call__(self, *args: Any) -> _NamedWriteLogger:  # noqa: ANN401 - structlog factory API
        name = str(args[0]) if args else self._default_name
        return _NamedWriteLogger(self._stream, name)


def _static_fields(fields: Mapping[str, str]) -> Processor:
    def add(_logger: WrappedLogger, _method: str, event_dict: EventDict) -> EventDict:
        event_dict.update(fields)  # mandatory context always wins over call-site keys
        return event_dict

    return add


def configure_logging(
    settings: LoggingSettings,
    service: str,
    version: str,
    *,
    stream: TextIO | None = None,
) -> None:
    """Configure structlog for the whole process.

    Every line carries ``ts`` (UTC ISO-8601), ``level``, ``logger``, ``event``, ``service``,
    ``version`` and any ids bound with :func:`bind_context`.

    Args:
        settings: ``logging.*`` settings (level, ``json``/``console`` format, caller info).
        service: Service name (e.g. ``roboprobe-api``).
        version: Software version.
        stream: Destination; defaults to stdout (docs/21 §5.1). CLIs pass stderr so stdout
            stays machine-readable.
    """
    out = stream if stream is not None else sys.stdout
    processors: list[Processor] = [
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.stdlib.add_logger_name,
        structlog.processors.TimeStamper(fmt="iso", utc=True, key="ts"),
        _static_fields({"service": service, "version": version}),
    ]
    if settings.include_caller:
        processors.append(
            structlog.processors.CallsiteParameterAdder(
                {
                    structlog.processors.CallsiteParameter.MODULE,
                    structlog.processors.CallsiteParameter.FUNC_NAME,
                    structlog.processors.CallsiteParameter.LINENO,
                }
            )
        )
    processors += [structlog.processors.StackInfoRenderer(), redact_secrets]
    if settings.format == "json":
        # Never render frame locals: they may hold secrets the redaction cannot see.
        tracebacks = structlog.processors.ExceptionRenderer(
            structlog.tracebacks.ExceptionDictTransformer(show_locals=False)
        )
        processors += [tracebacks, structlog.processors.JSONRenderer()]
    else:
        processors.append(
            structlog.dev.ConsoleRenderer(
                colors=out.isatty(),
                exception_formatter=structlog.dev.plain_traceback,
            )
        )
    structlog.configure(
        processors=processors,
        wrapper_class=structlog.make_filtering_bound_logger(
            logging.getLevelNamesMapping()[settings.level]
        ),
        logger_factory=_LoggerFactory(out, service),
        cache_logger_on_first_use=False,
    )


@contextmanager
def bind_context(**ids: object) -> Iterator[None]:
    """Bind correlation ids to every log line emitted inside the ``with`` block.

    Args:
        **ids: Values for keys in :data:`CONTEXT_KEYS` (converted to ``str``; ``None`` skipped).

    Yields:
        Nothing; previous bindings are restored on exit (safe for threads and asyncio tasks).

    Raises:
        ValueError: If a key is not in :data:`CONTEXT_KEYS`.
    """
    unknown = sorted(set(ids) - CONTEXT_KEYS)
    if unknown:
        msg = f"unknown log context keys: {unknown}; allowed: {sorted(CONTEXT_KEYS)}"
        raise ValueError(msg)
    values = {key: str(value) for key, value in ids.items() if value is not None}
    with structlog.contextvars.bound_contextvars(**values):
        yield
