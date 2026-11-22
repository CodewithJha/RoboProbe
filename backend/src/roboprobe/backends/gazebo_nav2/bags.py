"""Gazebo recording policy and rosbag2 output discovery (T-097b, FR-SIM-005)."""

from __future__ import annotations

import os
import shutil
from pathlib import Path
from typing import Protocol

from roboprobe.core.settings.backends import GazeboNav2Settings
from roboprobe.core.types import Verdict

_BAG_DIRECTORY = "bag"
_MCAP_MAGIC = b"\x89MCAP0\r\n"


class _BagRun(Protocol):
    phase: str
    source_verdict: Verdict | None


def should_record_bag(run: _BagRun, settings: GazeboNav2Settings) -> bool:
    """Resolve the policy before starting the episode using the replay source's verdict."""
    if settings.record_bag != "failures":
        return settings.record_bag == "always"
    return run.phase in {"confirm", "manual"} or (
        run.phase == "replay" and run.source_verdict is Verdict.FAIL
    )


def clear_episode_bag(workdir: Path) -> None:
    """Discard stale recorder output before a retry starts."""
    directory = workdir / _BAG_DIRECTORY
    if not directory.is_symlink() and directory.is_dir():
        shutil.rmtree(directory)
    else:
        directory.unlink(missing_ok=True)


def find_episode_bag(workdir: Path) -> Path | None:
    """Find the single, finalized MCAP emitted by the episode's unsplit recorder."""
    directory = workdir / _BAG_DIRECTORY
    if directory.is_symlink():
        return None
    files = list(directory.glob("*.mcap"))
    if len(files) != 1:
        return None
    (path,) = files
    if path.is_symlink() or not path.is_file():
        return None
    with path.open("rb") as file:
        if file.read(len(_MCAP_MAGIC)) != _MCAP_MAGIC:
            return None
        end = file.seek(-len(_MCAP_MAGIC), os.SEEK_END)
        if end <= len(_MCAP_MAGIC) or file.read() != _MCAP_MAGIC:
            return None
    return path
