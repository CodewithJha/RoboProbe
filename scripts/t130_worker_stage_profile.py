"""Collect worker execution profiles for a short T-130 diagnostic."""

from __future__ import annotations

import cProfile
import pstats
import sys
from pathlib import Path

import load_campaign

_EXECUTION_STAGES = {
    "execute", "_load_context", "materialize", "run_episode", "judge", "write_trace",
    "_build_manifest", "hash_uv_lock", "hash_file_sha256", "_upload", "put",
    "claim", "mark_running", "mark_evaluating", "_transition", "complete",
    "replace_for_run", "append", "validate",
}


def run_worker(profile_path: str) -> None:
    from roboprobe.cli.main import app
    from roboprobe.runner.worker import WorkerProcess

    profile = cProfile.Profile()
    original_execute = WorkerProcess.execute

    def profiled_execute(worker, *args, **kwargs):
        return profile.runcall(original_execute, worker, *args, **kwargs)

    WorkerProcess.execute = profiled_execute
    try:
        app()
    finally:
        profile.dump_stats(profile_path)


def main(output: Path) -> int:
    launch = load_campaign._run_process

    def start(executable, arguments, env, log):
        if arguments[0] == "worker":
            executable = Path(sys.executable)
            arguments = [
                str(Path(__file__).resolve()), "worker",
                str(log.with_suffix(".pstats")), *arguments,
            ]
        return launch(executable, arguments, env, log)

    load_campaign._run_process = start
    status = load_campaign.main(
        ["--workers", "1,8", "--runs", "400", "--backend", "benchmark", "--out", str(output)]
    )
    if status:
        return status
    for count in (1, 8):
        paths = sorted(output.glob(f"t130-*/workers-{count}/worker-*.pstats"))
        if len(paths) != count:
            raise RuntimeError(f"Expected {count} worker profiles, found {len(paths)}")
        profile = pstats.Stats(*(str(path) for path in paths))
        print(f"=== {count} workers; 400 episodes; aggregate cProfile wall seconds ===")
        print("calls  exclusive  inclusive  function")
        relevant = []
        for (file, _line, function), (_primitive, calls, own, total, _callers) in (
            profile.stats.items()
        ):
            if "/roboprobe/" in file and function in _EXECUTION_STAGES:
                relevant.append((total, calls, own, file.split("/roboprobe/")[-1], function))
        for total, calls, own, file, function in sorted(relevant, reverse=True):
            print(f"{calls:5d}  {own:9.3f}  {total:9.3f}  {file}:{function}")
    return 0


if __name__ == "__main__":
    if sys.argv[1] == "worker":
        sys.argv.pop(1)
        run_worker(sys.argv.pop(1))
    else:
        raise SystemExit(main(Path(sys.argv[1])))
