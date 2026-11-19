"""Unit tests for scripts/check_adr_index.py.

Stdlib unittest only: ``python3 -m unittest discover -s scripts/tests``.
"""

from __future__ import annotations

import contextlib
import importlib.util
import io
import sys
import tempfile
import unittest
from pathlib import Path

_SCRIPT = Path(__file__).resolve().parents[1] / "check_adr_index.py"
_spec = importlib.util.spec_from_file_location("check_adr_index", _SCRIPT)
if _spec is None or _spec.loader is None:
    raise ImportError(_SCRIPT)
check_adr_index = importlib.util.module_from_spec(_spec)
sys.modules["check_adr_index"] = check_adr_index
_spec.loader.exec_module(check_adr_index)

ADR_BODY = "# ADR-{n}: Title\n\n| Field | Value |\n|-------|-------|\n| Status | {status} |\n"
HEADER = "| ADR | Title | Status |\n|-----|-------|--------|\n"


def _row(number: str, prefix: str = "", status: str = "Accepted") -> str:
    return f"| [ADR-{number}]({prefix}ADR-{number}-topic.md) | Topic | {status} |\n"


class CheckAdrIndexTest(unittest.TestCase):
    """End-to-end checks of ``main`` against a temporary repository layout."""

    def setUp(self) -> None:
        """Create two Accepted ADRs."""
        self._tmp = tempfile.TemporaryDirectory()
        self.root = Path(self._tmp.name)
        self.adr_dir = self.root / "docs" / "adr"
        self.adr_dir.mkdir(parents=True)
        for number in ("0001", "0002"):
            self._write_adr(number, "Accepted")

    def tearDown(self) -> None:
        """Remove the temporary repository."""
        self._tmp.cleanup()

    def _write_adr(self, number: str, status: str) -> None:
        (self.adr_dir / f"ADR-{number}-topic.md").write_text(
            ADR_BODY.format(n=number, status=status), encoding="utf-8"
        )

    def _write_indexes(self, readme_rows: str, doc15_rows: str) -> None:
        (self.adr_dir / "README.md").write_text(
            "# ADRs\n\n" + HEADER + readme_rows, encoding="utf-8"
        )
        doc15 = (
            "# 15\n\n## 2. ADR index\n\n"
            + HEADER
            + doc15_rows
            + "\n## 3. Next\n\n"
            + _row("0099", "adr/")
        )
        (self.root / "docs" / "15-tech-stack-and-adrs.md").write_text(doc15, encoding="utf-8")

    def _run(self) -> tuple[int, str]:
        stderr = io.StringIO()
        with contextlib.redirect_stderr(stderr), contextlib.redirect_stdout(io.StringIO()):
            code = check_adr_index.main(["--root", str(self.root)])
        return code, stderr.getvalue()

    def test_consistent_indexes_pass(self) -> None:
        """Both indexes listing exactly the ADR files pass."""
        self._write_indexes(
            _row("0001") + _row("0002"), _row("0001", "adr/") + _row("0002", "adr/")
        )
        self.assertEqual(self._run(), (check_adr_index.EXIT_OK, ""))

    def test_rows_outside_the_named_section_are_ignored(self) -> None:
        """Only the named section of doc 15 is parsed."""
        # The fixture places ADR-0099 under "## 3. Next"; it must not count as a dangling entry.
        self._write_indexes(
            _row("0001") + _row("0002"), _row("0001", "adr/") + _row("0002", "adr/")
        )
        code, _ = self._run()
        self.assertEqual(code, check_adr_index.EXIT_OK)

    def test_unlisted_adr_fails(self) -> None:
        """An ADR file missing from an index fails."""
        self._write_indexes(_row("0001"), _row("0001", "adr/") + _row("0002", "adr/"))
        code, err = self._run()
        self.assertEqual(code, check_adr_index.EXIT_MISMATCH)
        self.assertIn("ADR-0002-topic.md is not listed", err)

    def test_dangling_link_fails(self) -> None:
        """An index row pointing at a non-existent ADR fails."""
        rows = _row("0001") + _row("0002") + _row("0003")
        self._write_indexes(rows, _row("0001", "adr/") + _row("0002", "adr/"))
        code, err = self._run()
        self.assertEqual(code, check_adr_index.EXIT_MISMATCH)
        self.assertIn("ADR-0003 links to missing file", err)

    def test_duplicate_row_fails(self) -> None:
        """An ADR listed twice fails."""
        self._write_indexes(
            _row("0001") + _row("0001") + _row("0002"), _row("0001", "adr/") + _row("0002", "adr/")
        )
        code, err = self._run()
        self.assertEqual(code, check_adr_index.EXIT_MISMATCH)
        self.assertIn("listed more than once", err)

    def test_status_mismatch_fails(self) -> None:
        """An index status differing from the ADR Status field fails."""
        self._write_adr("0002", "Superseded by ADR-0003")
        self._write_indexes(
            _row("0001") + _row("0002"), _row("0001", "adr/") + _row("0002", "adr/")
        )
        code, err = self._run()
        self.assertEqual(code, check_adr_index.EXIT_MISMATCH)
        self.assertIn("status 'Accepted' != 'Superseded by ADR-0003'", err)

    def test_missing_section_is_a_usage_error(self) -> None:
        """A missing index section is reported as a usage error."""
        self._write_indexes(_row("0001") + _row("0002"), "")
        doc15 = self.root / "docs" / "15-tech-stack-and-adrs.md"
        doc15.write_text("# 15\n\nno index here\n", encoding="utf-8")
        code, err = self._run()
        self.assertEqual(code, check_adr_index.EXIT_USAGE)
        self.assertIn("no heading containing", err)


if __name__ == "__main__":
    unittest.main()
