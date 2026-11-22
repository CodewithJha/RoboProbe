#!/usr/bin/env python3
"""Measure MET-06 for stored campaign medoids using deterministic RoboProbe replays."""

from __future__ import annotations

import argparse
import csv
import json
import subprocess
from dataclasses import asdict, dataclass
from pathlib import Path
from statistics import fmean
from uuid import UUID

REPEATS = 5


@dataclass(frozen=True, slots=True)
class Medoid:
    """One failure mode selected from a completed campaign."""

    campaign_id: str
    mode: str
    medoid_run_id: str


def load_medoids(path: Path) -> list[Medoid]:
    """Read an explicit campaign and mode inventory before enqueuing any replays."""
    with path.open(encoding="utf-8", newline="") as source:
        rows = csv.DictReader(source)
        required = {"campaign_id", "mode", "medoid_run_id"}
        if not required.issubset(rows.fieldnames or ()):
            message = "medoid CSV requires campaign_id, mode, medoid_run_id columns"
            raise ValueError(message)
        medoids = [
            Medoid(
                str(UUID(row["campaign_id"])), row["mode"].strip(), str(UUID(row["medoid_run_id"]))
            )
            for row in rows
        ]
    if not medoids:
        message = "medoid CSV contains no modes"
        raise ValueError(message)
    if any(not medoid.mode for medoid in medoids):
        message = "every medoid must have a mode code"
        raise ValueError(message)
    keys = {(medoid.campaign_id, medoid.mode) for medoid in medoids}
    if len(keys) != len(medoids):
        message = "medoid CSV contains duplicate campaign and mode pairs"
        raise ValueError(message)
    return medoids


def replay_medoid(executable: str, medoid: Medoid) -> tuple[float, dict[str, object]]:
    """Replay a source seed five times and retain the CLI's verdict and class comparisons."""
    # The operator selects the executable. The only CSV argument is a canonical UUID.
    result = subprocess.run(  # noqa: S603
        [executable, "--json", "replay", "--repeats", str(REPEATS), medoid.medoid_run_id],
        check=True,
        stdout=subprocess.PIPE,
        text=True,
    )
    evidence = json.loads(result.stdout)
    if evidence["source_run_id"] != medoid.medoid_run_id or evidence["source_verdict"] is None:
        message = f"invalid replay source for {medoid.medoid_run_id}"
        raise ValueError(message)
    rows = evidence["rows"]
    agreements = sum(row["agree"] is True for row in rows)
    if (
        len(rows) != REPEATS
        or len({row["run_id"] for row in rows}) != REPEATS
        or {row["run_id"] for row in rows} != set(evidence["replay_ids"])
        or agreements != evidence["agreements"]
        or REPEATS - agreements != evidence["disagreements"]
    ):
        message = f"incomplete replay accounting for {medoid.medoid_run_id}"
        raise ValueError(message)
    return agreements / REPEATS, evidence


def main(argv: list[str] | None = None) -> int:
    """Write per-mode replay records and the mean agreement for each campaign."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("medoids", type=Path, help="CSV with campaign_id, mode and medoid_run_id")
    parser.add_argument("--output", type=Path, required=True, help="write replay evidence as JSON")
    parser.add_argument("--roboprobe", default="roboprobe", help="path to the RoboProbe CLI")
    args = parser.parse_args(argv)

    modes = []
    campaigns: dict[str, list[float]] = {}
    # Preserve completed evidence if a subsequent replay fails or the batch is interrupted.
    medoids = load_medoids(args.medoids)
    for medoid in medoids:
        agreement, evidence = replay_medoid(args.roboprobe, medoid)
        modes.append({**asdict(medoid), "agreement": agreement, "replay": evidence})
        campaigns.setdefault(medoid.campaign_id, []).append(agreement)
        report = {
            "repeats_per_mode": REPEATS,
            "planned_modes": len(medoids),
            "completed_modes": len(modes),
            "campaigns": {
                campaign: {"modes": len(values), "met_06": fmean(values)}
                for campaign, values in campaigns.items()
            },
            "modes": modes,
        }
        pending = args.output.with_suffix(args.output.suffix + ".tmp")
        pending.write_text(json.dumps(report, indent=2) + "\n", encoding="utf-8")
        pending.replace(args.output)
    return 3 if any(agreement < 1.0 for values in campaigns.values() for agreement in values) else 0


if __name__ == "__main__":
    raise SystemExit(main())
