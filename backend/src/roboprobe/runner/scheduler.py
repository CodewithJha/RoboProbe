"""In-flight target sizing for the campaign loop.

Implements: T-041a, FR-RUN-001
"""

from __future__ import annotations

import math

from roboprobe.core.settings.runner import RunnerSettings

__all__ = ["Scheduler"]


class Scheduler:
    """``target_inflight = ceil(min(batch_size, workers) * inflight_factor)``."""

    def __init__(self, settings: RunnerSettings) -> None:
        """Bind runner settings (inflight factor and max batch size)."""
        self._settings = settings

    def target_inflight(self, online_workers: int, batch_size: int) -> int:
        """Return how many PENDING+CLAIMED+RUNNING runs the loop should keep.

        Args:
            online_workers: Workers currently IDLE/BUSY/DRAINING for the backend.
            batch_size: Campaign ``batch_size`` (clamped by ``runner.max_batch_size``).
        """
        workers = max(0, online_workers)
        batch = max(0, min(batch_size, self._settings.max_batch_size))
        if workers == 0 or batch == 0:
            return 0
        return math.ceil(min(batch, workers) * self._settings.inflight_factor)
