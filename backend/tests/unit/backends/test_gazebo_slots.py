"""Check isolation across worker threads and after abrupt worker termination."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from multiprocessing import get_context
from pathlib import Path
from signal import SIGKILL, pause
from threading import Barrier
from typing import TYPE_CHECKING

import pytest

from roboprobe.backends.gazebo_nav2.slots import SlotAllocator, SlotsExhaustedError

if TYPE_CHECKING:
    from multiprocessing.synchronize import Event


@pytest.mark.parametrize(("base", "capacity"), [(-1, 1), (30, 0), (232, 2)])
def test_invalid_domain_ranges_are_rejected(tmp_path: Path, base: int, capacity: int) -> None:
    with pytest.raises(ValueError, match="valid ROS domain range"):
        SlotAllocator(tmp_path, domain_id_base=base, capacity=capacity, worker_id="worker")


def test_two_worker_threads_lease_independent_discovery_domains(tmp_path: Path) -> None:
    allocators = [
        SlotAllocator(tmp_path, domain_id_base=30, capacity=2, worker_id=worker)
        for worker in ("runner:193:0", "runner:193:1")
    ]
    ready = Barrier(2)

    def run(allocator: SlotAllocator) -> dict[str, str]:
        with allocator.reserve() as slot:
            ready.wait(timeout=10.0)
            return slot.environment()

    with ThreadPoolExecutor(2) as pool:
        first, second = pool.map(run, allocators)
    assert {first["ROS_DOMAIN_ID"], second["ROS_DOMAIN_ID"]} == {"30", "31"}
    assert first["GZ_PARTITION"] != second["GZ_PARTITION"]
    assert (
        first["ROS_AUTOMATIC_DISCOVERY_RANGE"]
        == second["ROS_AUTOMATIC_DISCOVERY_RANGE"]
        == ("LOCALHOST")
    )


def test_failed_episode_releases_lease_and_retains_lockfile(tmp_path: Path) -> None:
    allocator = SlotAllocator(tmp_path, domain_id_base=30, capacity=1, worker_id="one")
    msg = "episode failed"
    with pytest.raises(RuntimeError, match=msg), allocator.reserve() as slot:
        with pytest.raises(SlotsExhaustedError):
            allocator.acquire()
        raise RuntimeError(msg)

    path = tmp_path / "slots" / "0.lock"
    original_inode = path.stat().st_ino
    with allocator.reserve() as current:
        assert current.index == slot.index == 0
        allocator.release(slot)
        with pytest.raises(SlotsExhaustedError):
            allocator.acquire()
    assert path.stat().st_ino == original_inode


def _reserve_until_killed(root: Path, ready: Event) -> None:
    allocator = SlotAllocator(root, domain_id_base=30, capacity=1, worker_id="crashing")
    with allocator.reserve():
        ready.set()
        pause()


def test_kernel_releases_lock_of_killed_worker(tmp_path: Path) -> None:
    ctx = get_context("spawn")
    ready = ctx.Event()
    worker = ctx.Process(target=_reserve_until_killed, args=(tmp_path, ready))
    worker.start()
    allocator = SlotAllocator(tmp_path, domain_id_base=30, capacity=1, worker_id="replacement")
    try:
        assert ready.wait(15.0)
        with pytest.raises(SlotsExhaustedError):
            allocator.acquire()
    finally:
        if worker.is_alive():
            worker.kill()
        worker.join(timeout=10.0)
    assert worker.exitcode == -SIGKILL
    with allocator.reserve() as slot:
        assert slot.domain_id == 30
