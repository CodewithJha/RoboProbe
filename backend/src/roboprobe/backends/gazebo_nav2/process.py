"""Run and tear down one isolated Gazebo launch (T-096b, FR-SIM-003)."""

from __future__ import annotations

import os
import signal
import subprocess
import threading
from collections.abc import Callable, Mapping, Sequence
from contextlib import suppress
from dataclasses import dataclass
from enum import StrEnum
from pathlib import Path
from time import monotonic, sleep

import psutil  # type: ignore[import-untyped]

from roboprobe.core.errors import WorkerUnhealthy
from roboprobe.core.settings.backends import GazeboNav2Settings
from roboprobe.core.types import JsonValue

__all__ = ["EpisodeProcess", "ProcessExit", "ProcessState"]

_MANAGED_PROGRAMS = frozenset({"gz", "ros2", "parameter_bridge"})
_PARTITION = "GZ_PARTITION"


class ProcessState(StrEnum):
    """Why the launch stopped."""

    EXITED = "exited"
    CANCELED = "canceled"
    WALL_TIMEOUT = "wall_timeout"


@dataclass(frozen=True, slots=True)
class ProcessExit:
    """Launch state after the owned process group has been reaped."""

    state: ProcessState
    returncode: int | None


def _signal_group(group: int, signum: signal.Signals) -> None:
    # The group can exit between inspection and signal delivery.
    with suppress(ProcessLookupError):
        os.killpg(group, signum)


def _live_group(process: subprocess.Popen[bytes]) -> bool:
    if process.poll() is None:
        return True
    # The leader is reaped. Check for live descendants, excluding reparented zombies.
    try:
        for child in psutil.process_iter(["pid", "status"]):
            try:
                if (
                    child.info["status"] != psutil.STATUS_ZOMBIE
                    and os.getpgid(child.pid) == process.pid
                ):
                    return True
            except ProcessLookupError:
                continue
    except PermissionError:
        with suppress(ProcessLookupError):
            try:
                os.killpg(process.pid, 0)
            except PermissionError:
                return True
            return True
    return False


def _orphan_pids(partition: str | None) -> list[int]:
    if partition is None:
        return []
    matches: list[int] = []
    for process in psutil.process_iter(["name", "cmdline", "status"]):
        try:
            if process.info["status"] == psutil.STATUS_ZOMBIE:
                continue
            name = (process.info["name"] or "").split(maxsplit=1)
            arguments = process.info["cmdline"] or []
            if (
                any(Path(part).name in _MANAGED_PROGRAMS for part in (*name, *arguments))
                and process.environ().get(_PARTITION) == partition
            ):
                matches.append(process.pid)
        except (psutil.AccessDenied, psutil.NoSuchProcess, psutil.ZombieProcess):
            continue
    return sorted(matches)


class EpisodeProcess:
    """Start a separate session and supervise its entire process group."""

    def __init__(self, settings: GazeboNav2Settings, *, poll_interval_s: float) -> None:
        """Use the worker polling interval and Gazebo teardown policy."""
        self._settings = settings
        self._poll_interval_s = poll_interval_s

    def run(  # noqa: PLR0913 - explicit process environment and cancellation boundary
        self,
        command: Sequence[str],
        *,
        workdir: Path,
        env: Mapping[str, str],
        wall_timeout_s: float,
        cancel: threading.Event,
        on_progress: Callable[[float], None] | None = None,
    ) -> ProcessExit:
        """Wait for the launch exit, deadline, or cancellation and always run teardown."""
        logfile = workdir / "episode.log"
        with logfile.open("wb") as log:
            process = subprocess.Popen(  # noqa: S603 - fixed ROS executable and typed arguments
                command,
                cwd=workdir,
                env=dict(env),
                start_new_session=True,
                stdin=subprocess.DEVNULL,
                stdout=log,
                stderr=subprocess.STDOUT,
            )
            try:
                state = self._wait(process, wall_timeout_s, cancel, on_progress)
            finally:
                self._teardown(process, env.get(_PARTITION))
        return ProcessExit(state=state, returncode=process.returncode)

    def _wait(
        self,
        process: subprocess.Popen[bytes],
        timeout: float,
        cancel: threading.Event,
        on_progress: Callable[[float], None] | None,
    ) -> ProcessState:
        started = monotonic()
        while process.poll() is None:
            elapsed = monotonic() - started
            if elapsed >= timeout:
                return ProcessState.WALL_TIMEOUT
            if on_progress is not None:
                on_progress(elapsed / timeout)
            if cancel.wait(min(self._poll_interval_s, timeout - elapsed)):
                return ProcessState.CANCELED
        return ProcessState.EXITED

    def _wait_for_group(self, process: subprocess.Popen[bytes], duration_s: float) -> bool:
        deadline = monotonic() + duration_s
        while _live_group(process):
            remaining = deadline - monotonic()
            if remaining <= 0:
                return False
            sleep(min(self._poll_interval_s, remaining))
        return True

    def _teardown(self, process: subprocess.Popen[bytes], partition: str | None) -> None:
        stages = (
            (signal.SIGINT, self._settings.teardown_grace_s),
            (signal.SIGTERM, self._settings.teardown_term_wait_s),
            (signal.SIGKILL, self._poll_interval_s),
        )
        for signum, duration in stages:
            if not _live_group(process):
                break
            _signal_group(process.pid, signum)
            if self._wait_for_group(process, duration):
                break
        try:
            survivors = _orphan_pids(partition)
        except PermissionError as exc:
            msg = "worker cannot verify Gazebo process cleanup"
            raise WorkerUnhealthy(msg, context={"process_group": process.pid}) from exc
        if _live_group(process) or survivors:
            msg = "Gazebo episode left live processes after teardown"
            raise WorkerUnhealthy(
                msg,
                context={"process_group": process.pid, "orphan_pids": list[JsonValue](survivors)},
            )
