#!/usr/bin/env python3
"""Verify the expected release files and print the paths safe to pass to gh."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

_IMAGES = ("backend", "web", "gazebo")


def verify_sbom(path: Path) -> None:
    """Require a populated SPDX JSON document."""
    document = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(document, dict) or document.get("SPDXID") != "SPDXRef-DOCUMENT":
        msg = "expected an SPDX document"
        raise ValueError(msg)
    version = document.get("spdxVersion")
    namespace = document.get("documentNamespace")
    packages = document.get("packages")
    if (
        not isinstance(version, str)
        or not version.startswith("SPDX-2.")
        or not isinstance(namespace, str)
        or not namespace.strip()
        or not isinstance(packages, list)
        or not packages
        or any(
            not isinstance(package, dict)
            or not isinstance(package.get("name"), str)
            or not isinstance(package.get("SPDXID"), str)
            for package in packages
        )
    ):
        msg = "expected an SPDX 2.x version, namespace, and package inventory"
        raise ValueError(msg)


def verify_demo(path: Path) -> None:
    """Require the standalone HTML exported by the campaign report template."""
    html = path.read_text(encoding="utf-8").strip()
    if (
        not html.lower().startswith("<!doctype html>")
        or "<title>RoboProbe campaign report" not in html
        or not html.lower().endswith("</html>")
    ):
        msg = "expected a complete RoboProbe campaign HTML report"
        raise ValueError(msg)


def main(argv: list[str] | None = None) -> int:
    """Check the requested files before listing any attachment paths."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--sboms", type=Path, help="Directory of the three image SBOMs.")
    parser.add_argument("--demo", type=Path, help="Path to the generated campaign HTML report.")
    args = parser.parse_args(argv)
    if args.sboms is None and args.demo is None:
        parser.error("provide --sboms or --demo")

    assets: list[Path] = []
    try:
        if args.sboms is not None:
            for image in _IMAGES:
                path = args.sboms / f"roboprobe-{image}.spdx.json"
                verify_sbom(path)
                assets.append(path)
        if args.demo is not None:
            path = args.demo
            verify_demo(path)
            assets.append(path)
    except (OSError, ValueError) as exc:
        print(f"{path}: {exc}", file=sys.stderr)
        return 1

    for path in assets:
        print(path)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
