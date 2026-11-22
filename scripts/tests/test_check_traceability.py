"""Verify release traceability against real test declarations and closed issue links."""

from __future__ import annotations

import contextlib
import io
import json
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from _load import load_script

checker = load_script("check_traceability")
REPO = "CodewithJha/RoboProbe"
FIRST = f"https://github.com/{REPO}/issues/101"
SECOND = f"https://github.com/{REPO}/issues/102"


class CheckTraceabilityTest(unittest.TestCase):
    """Exercise the release checker against a small repository."""

    def setUp(self) -> None:
        """Install a real Python and TypeScript test declaration."""
        temp = tempfile.TemporaryDirectory()
        self.addCleanup(temp.cleanup)
        self.root = Path(temp.name)
        self._write(
            "docs/02-software-requirements-specification.md",
            "- **FR-SCN-001 [MVP]** — Description.\n"
            "| NFR-CFG-001 [MVP] | Config | Description | Test |\n"
            "| FR-SCN-002 | this is a summary, not a requirement declaration |\n",
        )
        self._write(
            "backend/tests/test_space.py",
            "class TestSpace:\n    def test_accepts_yaml(self):\n        assert True\n",
        )
        self._write(
            "web/e2e/specs/config.spec.ts",
            "test('reads the config', async () => {});\n"
            "// test('unimplemented config', async () => {});\n"
            "/*\ntest('commented config', async () => {});\n*/\n"
            "test.skip('skips the config', async () => {});\n",
        )
        self.snapshot = self.root / "closed.json"
        self.snapshot.write_text(
            json.dumps(
                [
                    {"url": FIRST, "stateReason": "COMPLETED"},
                    {"url": SECOND, "stateReason": "COMPLETED"},
                    {
                        "url": f"https://github.com/{REPO}/issues/103",
                        "stateReason": "NOT_PLANNED",
                    },
                ]
            ),
            encoding="utf-8",
        )

    def _write(self, name: str, value: str) -> None:
        path = self.root / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(value, encoding="utf-8")

    def _matrix(self, body: str) -> None:
        self._write(
            "docs/28-traceability-matrix.md",
            "# Traceability\n\n"
            "<!-- BEGIN REQUIREMENT EVIDENCE -->\n"
            "| Requirement | Test node | Closed issue |\n"
            "|-------------|-----------|--------------|\n"
            + body
            + "<!-- END REQUIREMENT EVIDENCE -->\n",
        )

    def _check(self, *, live: bool = False) -> tuple[int, str]:
        log = io.StringIO()
        with contextlib.redirect_stderr(log), contextlib.redirect_stdout(log):
            args = ["--root", str(self.root)]
            if not live:
                args.extend(["--closed-issues", str(self.snapshot)])
            code = checker.main(args)
        return code, log.getvalue()

    def test_valid_python_typescript_and_closed_links(self) -> None:
        """Accept exact node IDs from both test runners and verified GitHub URLs."""
        self._matrix(
            "| FR-SCN-001 | `backend/tests/test_space.py::TestSpace::test_accepts_yaml` | "
            f"[#101]({FIRST}) |\n"
            "| NFR-CFG-001 | `web/e2e/specs/config.spec.ts::reads the config` | "
            f"[#102]({SECOND}) |\n"
        )
        code, output = self._check()
        self.assertEqual(code, 0, output)
        self.assertIn("2 requirements have", output)

    def test_reports_missing_stale_and_nonclosed_evidence(self) -> None:
        """List missing rows or declarations and issues absent from the closed snapshot."""
        self._matrix(
            "| FR-SCN-001 | `backend/tests/test_space.py::test_missing` | "
            f"[#103](https://github.com/{REPO}/issues/103) |\n"
        )
        code, output = self._check()
        self.assertEqual(code, 1)
        self.assertIn("FR-SCN-001 has no existing test node", output)
        self.assertIn("FR-SCN-001 has no verified closed GitHub issue", output)
        self.assertIn("NFR-CFG-001 has no evidence row", output)

    def test_duplicate_and_unknown_ids_fail(self) -> None:
        """Reject ambiguous rows and IDs missing from the specification."""
        self._matrix("| FR-SCN-001 | — | — |\n| FR-SCN-001 | — | — |\n| FR-SCN-987 | — | — |\n")
        code, output = self._check()
        self.assertEqual(code, 1)
        self.assertIn("FR-SCN-001 has duplicate evidence rows", output)
        self.assertIn("FR-SCN-987 is not declared in the SRS", output)

    def test_empty_markers_and_malformed_snapshot_fail(self) -> None:
        """Separate malformed inputs from a completed audit with gaps."""
        code, output = self._check()
        self.assertEqual(code, 2)
        self.assertIn("traceability", output)
        self._matrix("| FR-SCN-001 | — | — |\n")
        self.snapshot.write_text("{}", encoding="utf-8")
        code, output = self._check()
        self.assertEqual(code, 2)
        self.assertIn("closed GitHub issue snapshot", output)

    def test_path_escape_commented_and_skipped_nodes_do_not_count(self) -> None:
        """Require confined source paths and active declarations."""
        for ref in (
            "../test_outside.py::test_outside",
            "web/e2e/specs/config.spec.ts::unimplemented config",
            "web/e2e/specs/config.spec.ts::commented config",
            "web/e2e/specs/config.spec.ts::skips the config",
            "web/e2e/specs/missing.spec.ts::reads the config",
        ):
            with self.subTest(ref=ref):
                self.assertFalse(checker.test_node_exists(self.root, ref))

    def test_live_github_query_and_error(self) -> None:
        """Use a read-only issue query and report GitHub unavailability."""
        self._matrix("| FR-SCN-001 | — | — |\n| NFR-CFG-001 | — | — |\n")
        with patch.object(
            checker.subprocess,
            "run",
            return_value=subprocess.CompletedProcess(["gh"], 0, self.snapshot.read_text()),
        ) as run:
            self.assertEqual(self._check(live=True)[0], 1)
            self.assertIn("url,stateReason", run.call_args.args[0])
        with patch.object(
            checker.subprocess, "run", side_effect=subprocess.TimeoutExpired("gh", 1)
        ):
            code, output = self._check(live=True)
        self.assertEqual(code, 2)
        self.assertIn("Authenticate gh", output)
