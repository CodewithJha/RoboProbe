"""Unit tests for scripts/check_audit.py (``python3 -m unittest discover -s scripts/tests``)."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from collections.abc import Mapping
from pathlib import Path

from _load import load_script

check_audit = load_script("check_audit")

OSV_RECORDS: dict[str, Mapping[str, object]] = {
    "GHSA-high-0001": {"database_specific": {"severity": "HIGH"}},
    "GHSA-low-0001": {"database_specific": {"severity": "LOW"}},
    "PYSEC-2026-1": {"database_specific": {}},
    "PYSEC-2026-2": {"aliases": ["CVE-2026-2", "GHSA-high-0001"]},
}


def fake_osv(vuln_id: str) -> Mapping[str, object]:
    """OSV lookup from the in-memory table; unknown IDs behave like a network error."""
    if vuln_id not in OSV_RECORDS:
        raise OSError(vuln_id)
    return OSV_RECORDS[vuln_id]


def pip_report(*vulns: tuple[str, list[str]]) -> dict[str, object]:
    """pip-audit JSON with one package carrying ``vulns`` as (id, aliases)."""
    return {
        "dependencies": [
            {"name": "pkg", "version": "1.0", "vulns": [{"id": i, "aliases": a} for i, a in vulns]},
            {"name": "torch", "skip_reason": "not on PyPI"},
        ],
    }


class CheckAuditTest(unittest.TestCase):
    """Severity gating, OSV lookup and the ignore file."""

    def setUp(self) -> None:
        """Temporary directory with an empty ignore file."""
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)
        self.ignore = self.dir / "ignore.txt"
        self.ignore.write_text("# comments only\n", encoding="utf-8")

    def tearDown(self) -> None:
        """Remove fixtures."""
        self._tmp.cleanup()

    def _run(self, report_flag: str, report: object) -> tuple[int, str]:
        path = self.dir / "report.json"
        path.write_text(json.dumps(report), encoding="utf-8")
        err = io.StringIO()
        argv = [report_flag, str(path), "--ignore-file", str(self.ignore)]
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = check_audit.main(argv, fetch=fake_osv)
        return code, err.getvalue()

    def test_high_python_finding_blocks_via_ghsa_alias(self) -> None:
        """Severity is resolved through a GHSA alias of a PYSEC advisory."""
        code, err = self._run("--pip-audit", pip_report(("PYSEC-2026-1", ["GHSA-high-0001"])))
        self.assertEqual(code, check_audit.EXIT_BLOCKING)
        self.assertIn("PYSEC-2026-1 (high)", err)

    def test_severity_follows_aliases_of_the_osv_record(self) -> None:
        """A bare PYSEC finding resolves through the GHSA alias listed in its OSV record."""
        code, err = self._run("--pip-audit", pip_report(("PYSEC-2026-2", [])))
        self.assertEqual(code, check_audit.EXIT_BLOCKING)
        self.assertIn("PYSEC-2026-2 (high)", err)

    def test_low_finding_is_reported_but_passes(self) -> None:
        """Findings below the threshold do not fail the job."""
        code, _ = self._run("--pip-audit", pip_report(("GHSA-low-0001", [])))
        self.assertEqual(code, check_audit.EXIT_OK)

    def test_unknown_severity_is_treated_as_critical(self) -> None:
        """No resolvable severity fails closed."""
        code, err = self._run("--pip-audit", pip_report(("PYSEC-2099-9", [])))
        self.assertEqual(code, check_audit.EXIT_BLOCKING)
        self.assertIn("(critical)", err)

    def test_ignored_alias_is_accepted(self) -> None:
        """An ignore entry matching any alias accepts the finding."""
        self.ignore.write_text("GHSA-high-0001  # not reachable from our code (owner, 2026-11)\n")
        code, _ = self._run("--pip-audit", pip_report(("PYSEC-2026-1", ["GHSA-high-0001"])))
        self.assertEqual(code, check_audit.EXIT_OK)

    def test_ignore_entry_without_justification_is_usage_error(self) -> None:
        """Every ignore entry needs a '# justification'."""
        self.ignore.write_text("GHSA-high-0001\n")
        code, err = self._run("--pip-audit", pip_report())
        self.assertEqual(code, check_audit.EXIT_USAGE)
        self.assertIn("needs a '# justification'", err)

    def test_pnpm_severity_is_used_directly(self) -> None:
        """Severity from pnpm advisories is used as-is: moderate passes, critical blocks."""
        advisories = {
            "1": {
                "module_name": "a",
                "severity": "moderate",
                "github_advisory_id": "GHSA-a",
                "cves": [],
            },
            "2": {
                "module_name": "b",
                "severity": "critical",
                "github_advisory_id": "GHSA-b",
                "cves": ["CVE-2026-1"],
                "findings": [{"version": "1.2.3"}],
            },
        }
        code, err = self._run("--pnpm-audit", {"advisories": advisories, "metadata": {}})
        self.assertEqual(code, check_audit.EXIT_BLOCKING)
        self.assertIn("node b 1.2.3: GHSA-b (critical)", err)
        self.assertNotIn("node a", err)

    def test_pnpm_error_output_is_usage_error(self) -> None:
        """A registry error object must not pass as a clean report."""
        code, err = self._run("--pnpm-audit", {"error": {"code": "ERR_PNPM_AUDIT_BAD_RESPONSE"}})
        self.assertEqual(code, check_audit.EXIT_USAGE)
        self.assertIn("not a pnpm audit report", err)


if __name__ == "__main__":
    unittest.main()
