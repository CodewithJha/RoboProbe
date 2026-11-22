"""Regression tests for the medoid agreement evidence script."""

from __future__ import annotations

import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from uuid import UUID

from _load import load_script

replay = load_script("replay_agreement")
CAMPAIGN = str(UUID(int=1))
SOURCE = str(UUID(int=2))
OTHER_SOURCE = str(UUID(int=3))


def result(source: str, matches: int) -> subprocess.CompletedProcess[str]:
    """Build the verdict and class summary returned by the RoboProbe CLI."""
    replay_ids = [str(UUID(int=index)) for index in range(4, 9)]
    rows = [
        {"run_id": run_id, "agree": index < matches}
        for index, run_id in enumerate(replay_ids)
    ]
    return subprocess.CompletedProcess(
        args=[],
        returncode=0,
        stdout=json.dumps(
            {
                "source_run_id": source,
                "source_verdict": "FAIL",
                "agreements": matches,
                "disagreements": 5 - matches,
                "replay_ids": replay_ids,
                "rows": rows,
            }
        ),
    )


class ReplayAgreementTest(unittest.TestCase):
    """Exercise the CSV inventory and completed evidence paths."""

    def test_campaign_mean_and_disagreement_status(self) -> None:
        """Average per-mode agreement and keep evidence even when one replay disagrees."""
        with tempfile.TemporaryDirectory() as temp:
            inventory = Path(temp) / "medoids.csv"
            output = Path(temp) / "report.json"
            inventory.write_text(
                "campaign_id,mode,medoid_run_id\n"
                f"{CAMPAIGN},first,{SOURCE}\n{CAMPAIGN},second,{OTHER_SOURCE}\n",
                encoding="utf-8",
            )
            with patch.object(
                replay.subprocess, "run", side_effect=[result(SOURCE, 5), result(OTHER_SOURCE, 4)]
            ) as run:
                status = replay.main([str(inventory), "--output", str(output)])
            self.assertEqual(status, 3)
            self.assertEqual(run.call_count, 2)
            self.assertEqual(run.call_args.args[0][-3:], ["--repeats", "5", OTHER_SOURCE])
            report = json.loads(output.read_text(encoding="utf-8"))
            self.assertEqual(report["campaigns"][CAMPAIGN], {"modes": 2, "met_06": 0.9})
            self.assertEqual(report["completed_modes"], report["planned_modes"])

    def test_rejects_duplicate_mode_inventory(self) -> None:
        """Catch duplicate campaign and mode entries before making database changes."""
        with tempfile.TemporaryDirectory() as temp:
            inventory = Path(temp) / "medoids.csv"
            inventory.write_text(
                "campaign_id,mode,medoid_run_id\n"
                f"{CAMPAIGN},duplicate,{SOURCE}\n{CAMPAIGN},duplicate,{OTHER_SOURCE}\n",
                encoding="utf-8",
            )
            with self.assertRaisesRegex(ValueError, "duplicate"):
                replay.load_medoids(inventory)

    def test_rejects_incomplete_replay_batch(self) -> None:
        """Incomplete replay accounting cannot pass the reproducibility gate."""
        partial = result(SOURCE, 5)
        payload = json.loads(partial.stdout)
        payload["rows"].pop()
        partial.stdout = json.dumps(payload)
        medoid = replay.Medoid(CAMPAIGN, "mode", SOURCE)
        with patch.object(replay.subprocess, "run", return_value=partial):
            with self.assertRaisesRegex(ValueError, "incomplete"):
                replay.replay_medoid("roboprobe", medoid)
