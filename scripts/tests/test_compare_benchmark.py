"""Unit tests for scripts/compare_benchmark.py (T-064)."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path

from _load import load_script

compare_benchmark = load_script("compare_benchmark")


class CompareBenchmarkTest(unittest.TestCase):
    """Relative regression gates for weekly analytic baselines."""

    def test_passes_within_tolerance(self) -> None:
        """Small drifts inside the tolerance band are accepted."""
        baseline = {
            "results": {
                "S-BO:branin": {"median_first_fail": 20.0},
                "S-PROBE:multi": {"median_first_fail": 40.0, "mean_modes": 3.0},
            }
        }
        current = {
            "results": {
                "S-BO:branin": {"median_first_fail": 22.0},
                "S-PROBE:multi": {"median_first_fail": 42.0, "mean_modes": 2.9},
            }
        }
        self.assertEqual(compare_benchmark.compare(baseline, current, tolerance=0.2), [])

    def test_flags_median_regression(self) -> None:
        """A large median_first_fail increase fails until tolerance is raised."""
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            base = root / "base.json"
            cur = root / "cur.json"
            base.write_text(
                json.dumps({"results": {"S-BO:branin": {"median_first_fail": 20.0}}}),
                encoding="utf-8",
            )
            cur.write_text(
                json.dumps({"results": {"S-BO:branin": {"median_first_fail": 30.0}}}),
                encoding="utf-8",
            )
            self.assertEqual(
                compare_benchmark.main([str(base), str(cur), "--tolerance", "0.2"]),
                compare_benchmark.EXIT_REGRESSION,
            )
            self.assertEqual(
                compare_benchmark.main([str(base), str(cur), "--tolerance", "0.6"]),
                compare_benchmark.EXIT_OK,
            )


if __name__ == "__main__":
    unittest.main()
