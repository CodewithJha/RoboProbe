"""Unit tests for scripts/check_licenses.py (``python3 -m unittest discover -s scripts/tests``)."""

from __future__ import annotations

import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from _load import load_script

check_licenses = load_script("check_licenses")
ALLOWED = check_licenses.load_allowed(check_licenses.DEFAULT_ALLOWED_FILE)


class IsAllowedTest(unittest.TestCase):
    """SPDX expression and classifier evaluation against the real allow-list."""

    def test_permissive_and_weak_copyleft_pass(self) -> None:
        """Common OSI licences used by our dependencies are allowed."""
        for name in ("MIT", "BSD-3-Clause", "Apache Software License", "LGPL-3.0-only", "mpl-2.0"):
            with self.subTest(name=name):
                self.assertTrue(check_licenses.is_allowed(name, ALLOWED))

    def test_expressions(self) -> None:
        """OR needs one allowed side, AND needs all, WITH keeps the base licence."""
        cases = {
            "MIT OR GPL-3.0-only": True,
            "(GPL-3.0-only OR Apache-2.0)": True,
            "MIT AND GPL-3.0-only": False,
            "Apache-2.0 AND (MIT OR BSD-2-Clause)": True,
            "Apache-2.0 WITH LLVM-exception AND BSL-1.0": True,
            "Apache Software License; MIT License": True,
            "GNU General Public License v3 (GPLv3); Proprietary": False,
        }
        for expression, expected in cases.items():
            with self.subTest(expression=expression):
                self.assertIs(check_licenses.is_allowed(expression, ALLOWED), expected)

    def test_gpl_non_osi_unknown_and_malformed_fail(self) -> None:
        """Strong copyleft, source-available, missing and unparsable licences are rejected."""
        for name in (
            "GPL-3.0-only",
            "AGPL-3.0-or-later",
            "SSPL-1.0",
            "UNKNOWN",
            "",
            "MIT AND (",
            "MIT)",
        ):
            with self.subTest(name=name):
                self.assertFalse(check_licenses.is_allowed(name, ALLOWED))


class MainTest(unittest.TestCase):
    """End-to-end over report files."""

    def setUp(self) -> None:
        """Temporary directory for report fixtures."""
        self._tmp = tempfile.TemporaryDirectory()
        self.dir = Path(self._tmp.name)

    def tearDown(self) -> None:
        """Remove fixtures."""
        self._tmp.cleanup()

    def _write(self, name: str, payload: object) -> Path:
        path = self.dir / name
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def _run(self, *argv: str) -> tuple[int, str]:
        err = io.StringIO()
        with contextlib.redirect_stderr(err), contextlib.redirect_stdout(io.StringIO()):
            code = check_licenses.main(list(argv))
        return code, err.getvalue()

    def test_clean_reports_pass(self) -> None:
        """Allowed licences in both ecosystems exit 0."""
        pip = self._write(
            "pip.json", [{"Name": "numpy", "Version": "2.0", "License": "BSD License"}]
        )
        pnpm = self._write("pnpm.json", {"MIT": [{"name": "react", "versions": ["19.0.0"]}]})
        code, _ = self._run("--pip-licenses", str(pip), "--pnpm-licenses", str(pnpm))
        self.assertEqual(code, check_licenses.EXIT_OK)

    def test_gpl_dependency_fails(self) -> None:
        """A GPL dependency is reported with ecosystem, name and licence."""
        pnpm = self._write("pnpm.json", {"GPL-3.0": [{"name": "copyleft", "versions": ["1.0.0"]}]})
        code, err = self._run("--pnpm-licenses", str(pnpm))
        self.assertEqual(code, check_licenses.EXIT_DISALLOWED)
        self.assertIn("node copyleft 1.0.0: 'GPL-3.0' not allowed", err)

    def test_malformed_report_is_usage_error(self) -> None:
        """A report missing required fields exits 2."""
        pip = self._write("pip.json", [{"Name": "x"}])
        code, _ = self._run("--pip-licenses", str(pip))
        self.assertEqual(code, check_licenses.EXIT_USAGE)


if __name__ == "__main__":
    unittest.main()
