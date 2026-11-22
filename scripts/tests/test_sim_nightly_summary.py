"""Verify that nightly summaries report real measurements and actual test outcomes."""

from pathlib import Path
from tempfile import TemporaryDirectory
from unittest import TestCase

from scripts.sim_nightly_summary import summarize


class SummaryTest(TestCase):
    """Exercise file formats produced by pytest and the episode manager."""

    def test_duration_and_rtf(self) -> None:
        """Report per-test durations and the real-time factor from a completed episode."""
        with TemporaryDirectory() as directory:
            results = Path(directory)
            (results / "simulation.xml").write_text(
                '<testsuites><testsuite><testcase name="nominal | warehouse" time="12.3"/>'
                "</testsuite></testsuites>",
                encoding="utf-8",
            )
            episode = results / "episodes" / "run"
            episode.mkdir(parents=True)
            (episode / "episode_done.json").write_text('{"rtf_mean": 0.75}', encoding="utf-8")
            markdown, success = summarize(results, annotate_junit=True)
            summarize(results, annotate_junit=True)
            junit = (results / "simulation.xml").read_text(encoding="utf-8")
        self.assertTrue(success)
        self.assertIn(r"| nominal \| warehouse | passed | 12.3 |", markdown)
        self.assertIn("| episodes/run | 0.750 |", markdown)
        self.assertEqual(junit.count('name="rtf_mean.episodes/run" value="0.750000"'), 1)

    def test_incomplete_suites_fail(self) -> None:
        """Distinguish missing reports, skipped tests, and test failures from a green run."""
        with TemporaryDirectory() as directory:
            results = Path(directory)
            self.assertFalse(summarize(results)[1])
            (results / "simulation.xml").write_text("<testsuites>", encoding="utf-8")
            self.assertFalse(summarize(results)[1])
            for status in ("skipped", "error", "failure"):
                with self.subTest(status=status):
                    (results / "simulation.xml").write_text(
                        f'<testsuites><testsuite><testcase name="test"><{status}/>'
                        "</testcase></testsuite></testsuites>",
                        encoding="utf-8",
                    )
                    self.assertFalse(summarize(results)[1])
