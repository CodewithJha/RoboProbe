"""Oracle port: pure robustness-valued detectors (docs/05 §6, docs/08).

Implements: FR-ORC-001, FR-ORC-002
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import ClassVar, Literal

from roboprobe.core.settings import OracleThresholds
from roboprobe.core.types import FailureClass, OracleResult, TaskSpec, Trace

__all__ = ["Oracle"]


class Oracle(ABC):
    """Pure function of a recorded trace, task spec and injected thresholds."""

    PLUGIN_API_VERSION: ClassVar[int] = 1
    id: ClassVar[str]
    failure_class: ClassVar[FailureClass]
    severity: ClassVar[Literal["failure", "warning"]]

    def __init__(self, thresholds: OracleThresholds) -> None:
        """Store campaign-resolved oracle thresholds (docs/27 §4.6)."""
        self.thresholds = thresholds

    @abstractmethod
    def evaluate(self, trace: Trace, task: TaskSpec) -> OracleResult:
        """Return robustness ``r ∈ [-1, 1]`` (negative iff violated)."""
