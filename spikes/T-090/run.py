"""Run one or two native containers and sample their Docker resource use."""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path
from time import monotonic, sleep
from uuid import uuid4


def run(count: int, software: bool, directory: Path, timeout_s: int, synchronize: bool) -> None:
    directory.mkdir(parents=True)
    barrier = (directory / "barrier").resolve()
    if synchronize:
        barrier.mkdir()
    token = uuid4().hex[:8]
    measurement = Path(__file__).resolve().with_name("measure.py")
    trials: list[tuple[str, subprocess.Popen[bytes]]] = []
    with directory.joinpath("docker-stats.jsonl").open("w") as samples:
        started = monotonic()
        try:
            for i in range(count):
                name = f"roboprobe-t090-{token}-{i + 1}"
                results = directory / str(i + 1)
                results.mkdir()
                args = [
                    "docker",
                    "run",
                    "--rm",
                    "--pull",
                    "never",
                    "--name",
                    name,
                    "--label",
                    "org.roboprobe.purpose=t090-gazebo-spike",
                    "-e",
                    f"ROS_DOMAIN_ID={80 + i}",
                    "-e",
                    f"GZ_PARTITION={name}",
                    "-e",
                    "RMW_IMPLEMENTATION=rmw_cyclonedds_cpp",
                    "-e",
                    "ROS_AUTOMATIC_DISCOVERY_RANGE=LOCALHOST",
                    "-e",
                    "QT_QPA_PLATFORM=offscreen",
                    "-e",
                    "EGL_PLATFORM=surfaceless",
                    "-v",
                    f"{measurement}:/spike/measure.py:ro",
                    "-v",
                    f"{results.resolve()}:/results",
                ]
                if software:
                    args.extend(("-e", "LIBGL_ALWAYS_SOFTWARE=1"))
                if synchronize:
                    args.extend(("-v", f"{barrier}:/barrier"))
                args.extend(
                    (
                        "roboprobe-t090-local:jazzy",
                        "python3",
                        "-u",
                        "/spike/measure.py",
                        "--output",
                        "/results",
                        "--timeout",
                        str(timeout_s),
                    )
                )
                if synchronize:
                    args.extend(
                        (
                            "--ready-dir",
                            "/barrier",
                            "--slot",
                            str(i + 1),
                            "--participants",
                            str(count),
                        )
                    )
                with results.joinpath("driver.log").open("wb") as log:
                    process = subprocess.Popen(args, stdout=log, stderr=subprocess.STDOUT)
                trials.append((name, process))
            while monotonic() - started <= timeout_s + 30:
                live = [name for name, process in trials if process.poll() is None]
                if not live:
                    break
                try:
                    snapshot = subprocess.run(
                        ["docker", "stats", "--no-stream", "--format", "{{json .}}", *live],
                        capture_output=True,
                        text=True,
                        check=False,
                        timeout=8,
                    )
                except subprocess.TimeoutExpired:
                    sleep(2)
                    continue
                for line in snapshot.stdout.splitlines():
                    sample = json.loads(line)
                    sample["wall_s"] = round(monotonic() - started, 3)
                    samples.write(json.dumps(sample) + "\n")
                samples.flush()
                sleep(2)
        finally:
            for name, process in trials:
                if process.poll() is None:
                    subprocess.run(
                        ["docker", "stop", "-t", "10", name], capture_output=True, check=False
                    )
                    process.wait()
    statuses = {name: process.returncode for name, process in trials}
    directory.joinpath("statuses.json").write_text(json.dumps(statuses, indent=2) + "\n")
    print(statuses, flush=True)
    if any(status != 0 for status in statuses.values()):
        raise SystemExit(1)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--count", type=int, choices=(1, 2), required=True)
    parser.add_argument("--software", action="store_true")
    parser.add_argument("--output", type=Path, required=True)
    parser.add_argument("--timeout", type=int, default=180)
    parser.add_argument(
        "--synchronize", action="store_true", help="Wait for both instances before sending goals."
    )
    args = parser.parse_args()
    if args.synchronize and args.count != 2:
        parser.error("--synchronize requires --count 2")
    run(args.count, args.software, args.output, args.timeout, args.synchronize)
