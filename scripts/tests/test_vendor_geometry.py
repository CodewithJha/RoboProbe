"""Regression tests for ROS vendoring drift (T-093a)."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from _load import load_script

vendor_geometry = load_script("vendor_geometry")


class VendorGeometryTest(unittest.TestCase):
    """Verify copied sources and detect edits in either direction."""

    def test_fails_when_source_or_vendored_code_changes(self) -> None:
        """Changing a source hash or a generated import fails the drift check."""
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            source = root / "backend/src/roboprobe/geometry"
            source.mkdir(parents=True)
            module = source / "sample.py"
            module.write_text("from roboprobe.geometry import radius\n", encoding="utf-8")
            self.assertEqual(vendor_geometry.vendor(root, check=False), ())
            self.assertEqual(vendor_geometry.vendor(root, check=True), ())

            module.write_text("from roboprobe.geometry import diameter\n", encoding="utf-8")
            changed = vendor_geometry.vendor(root, check=True)
            self.assertTrue(any(path.endswith("/sample.py") for path in changed))
            self.assertTrue(any(path.endswith("/manifest.json") for path in changed))
            vendor_geometry.vendor(root, check=False)
            self.assertEqual(vendor_geometry.vendor(root, check=True), ())

            copy = next((root / "ros_ws").rglob("sample.py"))
            self.assertIn("from roboprobe_ros._vendor.geometry", copy.read_text(encoding="utf-8"))
            copy.write_text("invalid\n", encoding="utf-8")
            self.assertEqual(
                vendor_geometry.vendor(root, check=True), (copy.relative_to(root).as_posix(),)
            )
