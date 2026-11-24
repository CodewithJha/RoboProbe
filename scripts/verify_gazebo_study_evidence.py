"""Verify restored Gazebo study evidence without running the simulator."""

from __future__ import annotations

import hashlib
import json
import math
import subprocess
import sys
import time
from uuid import UUID
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PG = "roboprobe-gazebo-evidence"


def load(path):
    return json.loads(path.read_text())


def digest(path):
    with path.open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def command(*args, **kwargs):
    return subprocess.run(args, check=True, **kwargs)


def postgres():
    command("docker", "run", "-d", "--network", "none", "--name", PG,
            "-e", "POSTGRES_HOST_AUTH_METHOD=trust", "postgres:17")
    for _ in range(60):
        if subprocess.run(("docker", "exec", PG, "pg_isready", "-h", "127.0.0.1",
                           "-U", "postgres"), capture_output=True, check=False).returncode == 0:
            return
        time.sleep(1)
    raise RuntimeError("PostgreSQL did not become ready")


def restore(name, path):
    command("docker", "exec", PG, "createdb", "-U", "postgres", name)
    with path.open("rb") as stream:
        command("docker", "exec", "-i", PG, "pg_restore", "-U", "postgres",
                "--exit-on-error", "--no-owner", "--no-privileges", "-d", name, stdin=stream)


def rows(database, select):
    result = command("docker", "exec", PG, "psql", "-XqtA", "-v", "ON_ERROR_STOP=1",
                     "-U", "postgres", "-d", database, "-c",
                     "SELECT row_to_json(evidence_row) FROM (" + select + ") AS evidence_row",
                     capture_output=True, text=True)
    return [json.loads(line) for line in result.stdout.splitlines()]


def save(output, name, document):
    output.mkdir(exist_ok=True)
    (output / name).write_text(json.dumps(document, indent=2, sort_keys=True) + "\n")


def verify_exp05(tmp):
    expected = {(arm, replicate) for arm in ("profile_A", "profile_B") for replicate in range(3)}
    originals = sorted((tmp / "exp05").glob("exp05-*-rep*-attempt1"))
    assert len(originals) == len(expected)
    design = ROOT / "configs/experiments/exp05_profiles.yaml"
    assert digest(design) == "ce40a7f73893dc10f1ae04c5af53f04bb4f31cc723d3f142c6692705db10b24a"
    profiles = {
        "profile_A": ("tb4_nav2_default", "125ce5539a41d8b39ef1d850dbead8aee02e2fac16f1c9708441eb7ece6a4944"),
        "profile_B": ("tb4_nav2_tuned", "65072c480d58e780282a8536e903bb32a2a88db31146631cb9592474f937edfb"),
    }
    results = {}
    for index, source in enumerate(originals):
        meta = load(source / "collection.json")
        cell = meta["cell"]
        identity = cell["strategy_label"], cell["experiment_rep"]
        assert identity in expected and identity not in results
        assert meta["config_sha256"] == digest(design)
        assert meta["campaign_status"] == "COMPLETED"
        assert meta["observed_episodes"] == meta["expected_episodes"] == cell["budget"] == 80
        assert digest(source / "runs.parquet") == meta["raw_parquet_sha256"]
        assert (cell["sut_profile_id"], meta["profile_sha256"]) == profiles[identity[0]]
        database = f"exp05_{index}"
        restore(database, source / "campaign.dump")
        campaign, = rows(database, "SELECT id,seed,status,budget,strategy_id,experiment_rep,sut_profile_id FROM campaigns")
        assert campaign == {
            "id": meta["campaign_id"], "seed": cell["seed"], "status": "COMPLETED",
            "budget": 80, "strategy_id": "S-PROBE", "experiment_rep": identity[1],
            "sut_profile_id": cell["sut_profile_id"],
        }, campaign
        observed = rows(database, "SELECT id,ordinal,status,seed,verdict,primary_failure,"
                        "x_unit,robustness,metrics,replay_of FROM runs ORDER BY ordinal")
        assert len(observed) == 80 and [row["ordinal"] for row in observed] == list(range(80))
        assert all(row["status"] == "DONE" and row["replay_of"] is None for row in observed)
        cli = load(source / "risk-analysis.json")
        assert cli["campaign_id"] == campaign["id"] and cli["kind"] == "full" and cli["waited"]
        analysis_id = str(UUID(cli["analysis_id"]))
        analyzed, = rows(database, "SELECT id,campaign_id,kind,status,n_runs,summary,report_sha256 "
                         f"FROM analyses WHERE id='{analysis_id}'")
        assert analyzed["campaign_id"] == campaign["id"] and analyzed["kind"] == "final", analyzed
        assert analyzed["status"] == "DONE" and analyzed["n_runs"] == 80, analyzed
        report_sha = analyzed["report_sha256"]
        report, = list((source / "artifacts").rglob(f"{report_sha}.json"))
        assert digest(report) == report_sha
        report_doc = load(report)
        assert report_doc["analysis_id"] == analysis_id and report_doc["summary"] == analyzed["summary"]
        volumes = analyzed["summary"]["volumes"]
        assert math.isclose(sum(volumes[k] for k in ("safe", "uncertain", "failure")), 1.0)
        score = volumes["robustness_score"]
        assert math.isclose(score, 1.0-volumes["failure"]-.5*volumes["uncertain"])
        counts = Counter(row["verdict"] for row in observed)
        failures = Counter(row["primary_failure"] for row in observed if row["verdict"] == "FAIL")
        result = {
            "arm": identity[0], "replicate": identity[1], "seed": campaign["seed"],
            "source_artifact": source.name, "campaign_id": campaign["id"], "analysis_id": analyzed["id"],
            "profile_id": cell["sut_profile_id"], "profile_sha256": meta["profile_sha256"],
            "runs_sha256": meta["raw_parquet_sha256"], "counts": dict(counts),
            "failure_classes": dict(failures), "volumes": volumes,
            "warnings": report_doc["warnings"],
        }
        destination = tmp / "exp05-verified"
        save(destination, f"{identity[0]}-rep{identity[1]}-rows.json", observed)
        save(destination, f"{identity[0]}-rep{identity[1]}-collection.json", meta)
        save(destination, f"{identity[0]}-rep{identity[1]}-analysis.json", analyzed)
        results[identity] = result
        print("EXP05_CELL " + json.dumps(result, sort_keys=True), flush=True)
    differences = []
    for replicate in range(3):
        a, b = (results[(arm, replicate)] for arm in ("profile_A", "profile_B"))
        assert a["seed"] == b["seed"] == a["volumes"]["seed"] == b["volumes"]["seed"]
        assert a["volumes"]["n"] == b["volumes"]["n"]
        differences.append(b["volumes"]["robustness_score"] - a["volumes"]["robustness_score"])
    result = {
        "source_run": 45120816975, "cells": list(results.values()),
        "matched_robustness_deltas": differences, "mean_delta": sum(differences) / len(differences),
    }
    save(tmp / "exp05-verified", "exp05-verified.json", result)
    print("EXP05_DELTAS " + json.dumps(differences), flush=True)


def verify_artifacts(database, source, inventory):
    verified = {}
    for row in rows(database, "SELECT run_id,kind,sha256,size_bytes,rel_path FROM artifacts ORDER BY kind"):
        key = row["run_id"], row["kind"]
        if row["run_id"] not in inventory:
            continue
        assert key not in verified, key
        path = source / "artifacts" / row["rel_path"]
        assert path.resolve().is_relative_to((source / "artifacts").resolve())
        assert path.stat().st_size == row["size_bytes"] and digest(path) == row["sha256"], path
        verified[key] = (row["sha256"], load(path) if row["kind"] == "manifest" else None)
    return verified


def replay_source(name, source, mode):
    restore(name, source / "replays.dump")
    run_id = mode["run_id"]
    entries = rows(name, "SELECT id,status,ordinal,seed,verdict,primary_failure,backend,"
                   "scenario_hash,scenario_values,x_unit,metrics,replay_of,"
                   "(proposal->>'fresh_seeds')::boolean AS fresh "
                   f"FROM runs WHERE id='{run_id}' OR replay_of='{run_id}' ORDER BY ordinal")
    original, = (row for row in entries if row["id"] == run_id)
    assert original["status"] == "DONE" and original["verdict"] == "FAIL"
    replays = [row for row in entries if row["replay_of"] == run_id]
    assert len(replays) == 10
    assert [row["fresh"] for row in replays] == [False] * 5 + [True] * 5
    assert [row["seed"] for row in replays[:5]] == [original["seed"]] * 5
    assert len({original["seed"], *(row["seed"] for row in replays[5:])}) == 6
    immutable = ("backend", "scenario_hash", "scenario_values", "x_unit")
    assert all(all(row[key] == original[key] for key in immutable) for row in replays)
    adjudicated = {row["id"] for row in entries if row["status"] == "DONE"}
    artifacts = verify_artifacts(name, source, adjudicated)
    for id in adjudicated:
        for kind in ("manifest", "trace", "log"):
            assert (id, kind) in artifacts, (id, kind, source)
    for phase, batch in (("same-seeds", replays[:5]), ("fresh-seeds", replays[5:])):
        cli = load(source / f"{phase}.json")
        assert cli["source_run_id"] == run_id and cli["source_verdict"] == "FAIL"
        assert cli["replay_ids"] == [row["id"] for row in batch]
        for row, summary in zip(batch, cli["rows"], strict=True):
            assert summary["run_id"] == row["id"]
            if summary["verdict"] is not None:
                assert (summary["verdict"], summary["primary_failure"]) == (
                    row["verdict"], row["primary_failure"])
    for row in entries:
        if row["status"] != "DONE":
            continue
        row["trace_sha256"] = artifacts[(row["id"], "trace")][0]
        _, row["manifest"] = artifacts[(row["id"], "manifest")]
        assert row["manifest"]["run_id"] == row["id"]
        assert row["manifest"]["seeds"]["run"] == row["seed"]
    return original, replays


def outcome(row):
    return row["verdict"], row["primary_failure"]


def semantic_provenance(manifest):
    backend = {key: value for key, value in manifest["backend"].items() if key != "image"}
    code = {key: value for key, value in manifest["roboprobe"].items() if key != "git_sha"}
    keys = ("space", "task", "sut_profile", "scenario", "config_snapshot")
    return {"backend": backend, "roboprobe": code, **{key: manifest[key] for key in keys}}


def verify_exp06(tmp):
    inventory = load(ROOT / "scripts/exp06_medoids.json")
    assert inventory["source_run"] == 45108261669 and len(inventory["medoids"]) == 10
    assert len(list((tmp / "exp06").glob("exp06-*-attempt1"))) == 10
    summaries = []
    for index, mode in enumerate(inventory["medoids"]):
        label = mode["mode"]
        source = tmp / "exp06" / f"exp06-{label}-attempt1"
        original, trials = replay_source(f"exp06_{index}", source, mode)
        retry_data = None
        if label == "EXP04-R3-FM02":
            retry_original, retry_trials = replay_source("exp06_recovery", tmp / "exp06-recovery", mode)
            assert retry_original == original
            assert all((first["ordinal"], first["seed"], first["fresh"]) ==
                       (second["ordinal"], second["seed"], second["fresh"])
                       for first, second in zip(trials, retry_trials, strict=True))
            assert [row["ordinal"] for row in trials if row["status"] != "DONE"] == [88, 89]
            retry_data = {"initial": trials, "retry": retry_trials}
            trials = [first if first["status"] == "DONE" else second
                      for first, second in zip(trials, retry_trials, strict=True)]
        assert len(trials) == 10 and all(row["status"] == "DONE" for row in trials)
        base = semantic_provenance(original["manifest"])
        changes = {
            row["id"]: sorted(key for key, value in semantic_provenance(row["manifest"]).items()
                              if base[key] != value)
            for row in trials
        }
        for row in trials[:5]:
            assert row["manifest"]["seeds"] == original["manifest"]["seeds"]
        discrepancies = [{
            "id": row["id"], "fresh": row["fresh"], "outcome": outcome(row),
            "drift": changes[row["id"]],
            "source_materialized": original["manifest"]["materialized"],
            "replay_materialized": row["manifest"]["materialized"],
            "source_host": original["manifest"]["host"], "replay_host": row["manifest"]["host"],
        } for row in trials if outcome(row) != outcome(original)]
        result = {
            "mode": label, "source_id": original["id"], "source_outcome": outcome(original),
            "same_matches": sum(outcome(row) == outcome(original) for row in trials[:5]),
            "fresh_matches": sum(outcome(row) == outcome(original) for row in trials[5:]),
            "trace_hash_matches": sum(row["trace_sha256"] == original["trace_sha256"] for row in trials),
            "manifest_nonruntime_changes": changes, "disagreements": discrepancies,
        }
        save(tmp / "exp06-verified", f"{label}.json",
             {"mode": mode, "source": original, "selected_replays": trials, "retry": retry_data})
        summaries.append(result)
        compact = {
            **{key: value for key, value in result.items() if key not in ("manifest_nonruntime_changes", "disagreements")},
            "disagreements": [{key: row[key] for key in ("id", "fresh", "outcome", "drift")}
                              for row in discrepancies],
        }
        print("EXP06_MODE " + json.dumps(compact, sort_keys=True), flush=True)
    result = {
        "source_run": 45119937477, "recovery_run": 45127477971, "modes": summaries,
        "same_matches": sum(row["same_matches"] for row in summaries), "same_total": 50,
        "fresh_matches": sum(row["fresh_matches"] for row in summaries), "fresh_total": 50,
    }
    save(tmp / "exp06-verified", "exp06-verified.json", result)
    print("EXP06_TOTAL " + json.dumps({k: v for k, v in result.items() if k != "modes"}), flush=True)


if __name__ == "__main__":
    tmp = Path(sys.argv[1])
    try:
        postgres()
        {"exp05": verify_exp05, "exp06": verify_exp06}[sys.argv[2]](tmp)
    finally:
        subprocess.run(("docker", "rm", "-f", PG), check=False)
