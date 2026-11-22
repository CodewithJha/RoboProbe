"""Lease host-local Gazebo and ROS discovery slots (T-097a, FR-SIM-004)."""

from __future__ import annotations

import fcntl
from contextlib import contextmanager
from dataclasses import dataclass, field
from hashlib import sha256
from typing import TYPE_CHECKING

from roboprobe.core.settings.backends import ROS_DOMAIN_ID_MAX

if TYPE_CHECKING:
    from collections.abc import Iterator
    from pathlib import Path
    from typing import BinaryIO

__all__ = ["Slot", "SlotAllocator", "SlotsExhaustedError"]


class SlotsExhaustedError(RuntimeError):
    """Every configured Gazebo slot is currently leased."""


@dataclass(frozen=True, slots=True)
class Slot:
    """One ROS domain and Gazebo partition, attached to an owned lock descriptor."""

    index: int
    domain_id: int
    partition: str
    _lease: BinaryIO = field(repr=False, compare=False)

    def environment(self) -> dict[str, str]:
        """Return the discovery isolation settings for a child process."""
        return {
            "ROS_DOMAIN_ID": str(self.domain_id),
            "GZ_PARTITION": self.partition,
            "ROS_AUTOMATIC_DISCOVERY_RANGE": "LOCALHOST",
        }


class SlotAllocator:
    """Coordinate simulator capacity across processes sharing a worker-host workdir root."""

    def __init__(
        self, workdir_root: Path, *, domain_id_base: int, capacity: int, worker_id: str
    ) -> None:
        """Reserve a valid contiguous ROS domain range for a host's simulator slots."""
        if capacity < 1 or domain_id_base < 0 or domain_id_base + capacity - 1 > ROS_DOMAIN_ID_MAX:
            msg = "Gazebo slot capacity and base must define a valid ROS domain range"
            raise ValueError(msg)
        self._directory = workdir_root / "slots"
        self._base = domain_id_base
        self._capacity = capacity
        self._worker_tag = sha256(worker_id.encode("utf-8")).hexdigest()[:12]

    def acquire(self) -> Slot:
        """Try every slot once, returning a lease or raising SlotsExhaustedError."""
        self._directory.mkdir(parents=True, exist_ok=True)
        for index in range(self._capacity):
            lease = (self._directory / f"{index}.lock").open("ab")
            try:
                fcntl.flock(lease.fileno(), fcntl.LOCK_EX | fcntl.LOCK_NB)
            except BlockingIOError:
                lease.close()
            except BaseException:
                lease.close()
                raise
            else:
                return Slot(index, self._base + index, f"rp_{self._worker_tag}_{index}", lease)
        msg = "All Gazebo host slots are in use"
        raise SlotsExhaustedError(msg)

    def release(self, slot: Slot) -> None:
        """Release the descriptor while retaining the lockfile inode for other contenders."""
        slot._lease.close()

    @contextmanager
    def reserve(self) -> Iterator[Slot]:
        """Release the slot on both normal completion and exceptions."""
        slot = self.acquire()
        try:
            yield slot
        finally:
            self.release(slot)
