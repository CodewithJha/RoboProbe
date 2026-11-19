"""RoboProbe error hierarchy with stable, machine-readable codes (docs/34 §5).

Every error carries a stable :class:`ErrorCode`, a human ``message`` and a structured, JSON-safe
``context``. Boundaries translate them: the API to RFC 9457 problem+json (docs/12 §1.1), workers to
``INVALID`` runs, the CLI to exit codes (docs/05 §11). Domain code raises; it never logs and
swallows. ``context`` must never contain secrets (docs/34 §6).

Hierarchy::

    RoboProbeError
    ├── ConfigError
    ├── ValidationError
    ├── NotFoundError
    ├── ConflictError
    ├── BackendError
    │   ├── EpisodeLaunchError
    │   └── EpisodeTimeoutError
    ├── OracleError
    ├── StrategyError
    │   └── ModelFitError
    ├── StoreError
    │   └── QueueError
    └── PluginError

Implements: FR-API-003
"""

from __future__ import annotations

from collections.abc import Mapping
from enum import StrEnum
from types import MappingProxyType
from typing import ClassVar

from roboprobe.core.types import JsonValue

__all__ = [
    "API_ERROR_CODES",
    "BackendError",
    "ConfigError",
    "ConflictError",
    "EpisodeLaunchError",
    "EpisodeTimeoutError",
    "ErrorCode",
    "ModelFitError",
    "NotFoundError",
    "OracleError",
    "PluginError",
    "QueueError",
    "RoboProbeError",
    "StoreError",
    "StrategyError",
    "ValidationError",
    "is_transient",
]


class ErrorCode(StrEnum):
    """Stable error codes. Values are part of the public API: extend, never rename."""

    # Codes exposed in the API error envelope (docs/12 §1.1).
    VALIDATION_ERROR = "VALIDATION_ERROR"
    NOT_FOUND = "NOT_FOUND"
    CAMPAIGN_INVALID_TRANSITION = "CAMPAIGN_INVALID_TRANSITION"
    SPACE_INVALID = "SPACE_INVALID"
    BACKEND_UNSUPPORTED_PARAM = "BACKEND_UNSUPPORTED_PARAM"
    NO_WORKERS = "NO_WORKERS"
    PRECONDITION_FAILED = "PRECONDITION_FAILED"
    UNAUTHORIZED = "UNAUTHORIZED"
    INTERNAL = "INTERNAL"
    # Default codes of the hierarchy below (docs/34 §5).
    CONFIG_INVALID = "CONFIG_INVALID"
    CONFLICT = "CONFLICT"
    BACKEND_ERROR = "BACKEND_ERROR"
    EPISODE_LAUNCH_FAILED = "EPISODE_LAUNCH_FAILED"
    EPISODE_TIMEOUT = "EPISODE_TIMEOUT"
    ORACLE_ERROR = "ORACLE_ERROR"
    STRATEGY_ERROR = "STRATEGY_ERROR"
    MODEL_FIT_FAILED = "MODEL_FIT_FAILED"
    STORE_ERROR = "STORE_ERROR"
    QUEUE_ERROR = "QUEUE_ERROR"
    PLUGIN_ERROR = "PLUGIN_ERROR"


API_ERROR_CODES: frozenset[ErrorCode] = frozenset(
    {
        ErrorCode.VALIDATION_ERROR,
        ErrorCode.NOT_FOUND,
        ErrorCode.CAMPAIGN_INVALID_TRANSITION,
        ErrorCode.SPACE_INVALID,
        ErrorCode.BACKEND_UNSUPPORTED_PARAM,
        ErrorCode.NO_WORKERS,
        ErrorCode.PRECONDITION_FAILED,
        ErrorCode.UNAUTHORIZED,
        ErrorCode.INTERNAL,
    }
)
"""Codes documented in the API error envelope (docs/12 §1.1)."""


def _rebuild[E: RoboProbeError](
    cls: type[E],
    message: str,
    code: ErrorCode,
    context: dict[str, JsonValue],
    transient: bool,
) -> E:
    """Reconstruct an error when unpickling (used by :meth:`RoboProbeError.__reduce__`)."""
    return cls(message, code=code, context=context, transient=transient)


class RoboProbeError(Exception):
    """Base class of every error raised by RoboProbe.

    Subclasses set :attr:`default_code` and :attr:`default_transient`; both can be overridden per
    instance.

    Attributes:
        code: Stable machine-readable code.
        message: Human-readable description (no secrets).
        context: Read-only, JSON-safe structured details (no secrets).
        transient: Whether retrying the failed operation may succeed (docs/34 §5).
    """

    default_code: ClassVar[ErrorCode] = ErrorCode.INTERNAL
    default_transient: ClassVar[bool] = False

    def __init__(
        self,
        message: str,
        *,
        code: ErrorCode | None = None,
        context: Mapping[str, JsonValue] | None = None,
        transient: bool | None = None,
    ) -> None:
        """Create an error.

        Args:
            message: Human-readable description.
            code: Overrides :attr:`default_code` (e.g. ``SPACE_INVALID`` on a ``ValidationError``).
            context: Structured details; copied and exposed read-only.
            transient: Overrides :attr:`default_transient`.
        """
        super().__init__(message)
        self.message = message
        self.code = ErrorCode(code) if code is not None else self.default_code
        self.context: Mapping[str, JsonValue] = MappingProxyType(dict(context or {}))
        self.transient = self.default_transient if transient is None else transient

    def __str__(self) -> str:
        """Return ``"<code>: <message>"``."""
        return f"{self.code}: {self.message}"

    def __repr__(self) -> str:
        """Return a debug representation including code and context."""
        context = dict(self.context)
        return f"{type(self).__name__}({self.message!r}, code={self.code!r}, context={context!r})"

    def __reduce__(self) -> tuple[object, tuple[object, ...]]:
        """Support pickling across processes (the read-only context proxy is not picklable)."""
        return (_rebuild, (type(self), self.message, self.code, dict(self.context), self.transient))


class ConfigError(RoboProbeError):
    """Configuration is missing, malformed or inconsistent (fail-fast at startup)."""

    default_code = ErrorCode.CONFIG_INVALID


class ValidationError(RoboProbeError):
    """Domain input failed validation (spaces, scenarios, campaign requests).

    Not to be confused with :class:`pydantic.ValidationError`: modules that use both should import
    this module (``from roboprobe.core import errors``) and refer to ``errors.ValidationError``.
    """

    default_code = ErrorCode.VALIDATION_ERROR


class NotFoundError(RoboProbeError):
    """A referenced entity does not exist."""

    default_code = ErrorCode.NOT_FOUND


class ConflictError(RoboProbeError):
    """An operation conflicts with current state, e.g. an invalid state transition."""

    default_code = ErrorCode.CONFLICT


class BackendError(RoboProbeError):
    """A simulator backend failed for infrastructure reasons (never a robot failure)."""

    default_code = ErrorCode.BACKEND_ERROR


class EpisodeLaunchError(BackendError):
    """The simulator episode could not be started; retryable (docs/34 §5)."""

    default_code = ErrorCode.EPISODE_LAUNCH_FAILED
    default_transient = True


class EpisodeTimeoutError(BackendError):
    """The episode exceeded its wall-clock watchdog."""

    default_code = ErrorCode.EPISODE_TIMEOUT


class OracleError(RoboProbeError):
    """An oracle could not evaluate a trace."""

    default_code = ErrorCode.ORACLE_ERROR


class StrategyError(RoboProbeError):
    """A selection strategy failed to propose scenarios."""

    default_code = ErrorCode.STRATEGY_ERROR


class ModelFitError(StrategyError):
    """A surrogate model (e.g. GP) failed to fit."""

    default_code = ErrorCode.MODEL_FIT_FAILED


class StoreError(RoboProbeError):
    """Persistence failed; adapters pass ``transient=True`` for e.g. serialisation failures."""

    default_code = ErrorCode.STORE_ERROR


class QueueError(StoreError):
    """The run queue failed to enqueue, claim or reap."""

    default_code = ErrorCode.QUEUE_ERROR


class PluginError(RoboProbeError):
    """A plugin could not be discovered, validated or instantiated."""

    default_code = ErrorCode.PLUGIN_ERROR


def is_transient(exc: BaseException) -> bool:
    """Return whether ``exc`` is a transient infrastructure error worth retrying.

    Only :class:`RoboProbeError` instances flagged ``transient`` qualify; domain validation errors
    and foreign exceptions are never retried (docs/34 §5).
    """
    return isinstance(exc, RoboProbeError) and exc.transient
