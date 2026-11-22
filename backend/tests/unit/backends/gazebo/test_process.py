"""Subprocess lifecycle tests with short-lived, real process groups (T-096b)."""

from __future__ import annotations

import os
import sys
import threading
from contextlib import suppress
from pathlib import Path
from time import monotonic

import psutil
import pytest

from roboprobe.backends.gazebo_nav2.process import EpisodeProcess, ProcessState
from roboprobe.core.errors import WorkerUnhealthy
from roboprobe.core.settings.backends import GazeboNav2Settings

pytestmark = pytest.mark.unit


def test_reports_process_exit_and_captures_output(tmp_path: Path) -> None:
    result = EpisodeProcess(GazeboNav2Settings(), poll_interval_s=0.01).run(
        [sys.executable, "-c", "print('gazebo episode'); raise SystemExit(11)"],
        workdir=tmp_path,
        env=dict(os.environ),
        wall_timeout_s=5.0,
        cancel=threading.Event(),
    )
    assert result.state is ProcessState.EXITED
    assert result.returncode == 11
    assert (tmp_path / "episode.log").read_text(encoding="utf-8") == "gazebo episode\n"


@pytest.mark.parametrize("cancel_on_start", [True, False])
def test_cancel_or_timeout_cleans_the_entire_process_group(
    tmp_path: Path, cancel_on_start: bool
) -> None:
    code = """
import os
import signal
import subprocess
import sys
from pathlib import Path
from time import sleep

signal.signal(signal.SIGINT, signal.SIG_IGN)
signal.signal(signal.SIGTERM, signal.SIG_IGN)
child = subprocess.Popen([sys.executable, "-c", "import time; time.sleep(60)"])
Path("started").write_text(str(os.getpgrp()) + " " + str(child.pid))
sleep(60)
"""
    cancel = threading.Event()
    started = monotonic()

    def progress(_: float) -> None:
        if cancel_on_start and (tmp_path / "started").is_file():
            cancel.set()

    result = EpisodeProcess(
        GazeboNav2Settings(teardown_grace_s=0.05, teardown_term_wait_s=0.05), poll_interval_s=0.01
    ).run(
        [sys.executable, "-c", code],
        workdir=tmp_path,
        env=dict(os.environ),
        wall_timeout_s=0.5,
        cancel=cancel,
        on_progress=progress,
    )
    assert result.state is (ProcessState.CANCELED if cancel_on_start else ProcessState.WALL_TIMEOUT)
    assert result.returncode == -9
    assert monotonic() - started < 2.0
    _parent, child = (tmp_path / "started").read_text(encoding="utf-8").split()
    with suppress(psutil.NoSuchProcess):
        assert psutil.Process(int(child)).status() == psutil.STATUS_ZOMBIE


def test_orphan_check_rejects_survivors_from_the_current_partition(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    calls: list[str | None] = []

    def retained(partition: str | None) -> list[int]:
        calls.append(partition)
        return [123]

    monkeypatch.setattr("roboprobe.backends.gazebo_nav2.process._orphan_pids", retained)
    with pytest.raises(WorkerUnhealthy, match="left live processes") as error:
        EpisodeProcess(GazeboNav2Settings(), poll_interval_s=0.01).run(
            [sys.executable, "-c", "pass"],
            workdir=tmp_path,
            env={**os.environ, "GZ_PARTITION": "unit-test-owned"},
            wall_timeout_s=2.0,
            cancel=threading.Event(),
        )
    assert calls == ["unit-test-owned"]
    assert error.value.context["orphan_pids"] == [123]
