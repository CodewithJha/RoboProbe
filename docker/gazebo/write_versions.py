"""Verify installed Gazebo apt pins and write the runtime provenance record."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path
from shutil import which


def _capture(program: str, *args: str) -> str:
    executable = which(program)
    if executable is None:
        msg = f"{program} is missing from the simulator image"
        raise FileNotFoundError(msg)
    return subprocess.check_output(  # noqa: S603 - fixed tools and separate package arguments
        [executable, *args], text=True
    ).strip()


def write_versions(pins_file: Path, output: Path) -> None:
    """Record simulator versions only after confirming all selected pins."""
    pins = dict(line.split("=") for line in pins_file.read_text().splitlines())
    installed = dict(
        line.split()
        for line in _capture(
            "dpkg-query", "-W", "-f", "${Package} ${Version}\n", *pins
        ).splitlines()
    )
    if installed != pins:
        msg = "installed Gazebo package versions do not match the selected pins"
        raise ValueError(msg)
    versions = {
        "ros_distro": os.environ["ROS_DISTRO"],
        "gz": _capture("gz", "sim", "--versions"),
        "nav2": installed["ros-jazzy-navigation2"].split("-", 1)[0],
        "rmw": "rmw_cyclonedds_cpp",
        "apt_packages": installed,
    }
    output.write_text(json.dumps(versions, indent=2, sort_keys=True) + "\n", encoding="utf-8")


if __name__ == "__main__":
    write_versions(Path(sys.argv[1]), Path(sys.argv[2]))
