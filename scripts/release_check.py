#!/usr/bin/env python3
"""Check that a release tag matches package versions and the changelog (T-124).

Compares ``vX.Y.Z`` (optional pre-release suffix) with ``backend/pyproject.toml`` and
``web/package.json``. ``ros_ws/src/roboprobe_ros/package.xml`` is included when that
package exists. The changelog must contain ``## [X.Y.Z] - YYYY-MM-DD``.

Exit status: 0 when the tag is consistent, 1 otherwise.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
import tomllib
from pathlib import Path

_TAG = re.compile(r"^v(?P<version>\d+\.\d+\.\d+)(?:-[0-9A-Za-z.]+)?$")
_SECTION = re.compile(r"^## \[(?P<version>\d+\.\d+\.\d+)\] - \d{4}-\d{2}-\d{2}\s*$", re.M)
_ROS = Path("ros_ws/src/roboprobe_ros/package.xml")


def release_version(tag: str) -> str | None:
    """Return ``X.Y.Z`` from ``vX.Y.Z`` or ``vX.Y.Z-rc.1``, else ``None``."""
    match = _TAG.fullmatch(tag.strip())
    if match is None:
        return None
    return match.group("version")


def package_versions(root: Path) -> dict[str, str]:
    """Read the version from each release manifest that exists under ``root``."""
    pyproject = tomllib.loads((root / "backend/pyproject.toml").read_text(encoding="utf-8"))
    package_json = json.loads((root / "web/package.json").read_text(encoding="utf-8"))
    found = {
        "backend/pyproject.toml": str(pyproject["project"]["version"]),
        "web/package.json": str(package_json["version"]),
    }
    ros = root / _ROS
    if ros.is_file():
        match = re.search(r"<version>([^<]+)</version>", ros.read_text(encoding="utf-8"))
        found[_ROS.as_posix()] = "" if match is None else match.group(1).strip()
    return found


def changelog_section(text: str, version: str) -> str | None:
    """Return the body under ``## [version]``, or ``None`` when the heading is absent."""
    match = _SECTION.search(text)
    while match is not None and match.group("version") != version:
        match = _SECTION.search(text, match.end())
    if match is None:
        return None
    rest = text[match.end() :]
    nxt = re.search(r"^## \[", rest, re.M)
    body = rest[: nxt.start()] if nxt else rest
    return body.strip() + "\n"


def problems(root: Path, tag: str) -> list[str]:
    """Describe version and changelog mismatches for ``tag``."""
    version = release_version(tag)
    if version is None:
        return [f"tag {tag!r} is not vX.Y.Z or vX.Y.Z-<pre>"]
    found: list[str] = []
    for path, value in package_versions(root).items():
        if value != version:
            found.append(f"{path} version {value!r} does not match {version}")
    changelog = (root / "CHANGELOG.md").read_text(encoding="utf-8")
    if changelog_section(changelog, version) is None:
        found.append(f"CHANGELOG.md has no '## [{version}] - YYYY-MM-DD' section")
    return found


def main(argv: list[str] | None = None) -> int:
    """Validate ``--tag`` or print its changelog section with ``--notes``."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--tag", required=True)
    parser.add_argument("--notes", action="store_true", help="Print the changelog section.")
    args = parser.parse_args(argv)
    mismatches = problems(args.root, args.tag)
    if mismatches:
        for line in mismatches:
            print(line, file=sys.stderr)
        return 1
    if args.notes:
        version = release_version(args.tag)
        if version is None:
            return 1
        text = (args.root / "CHANGELOG.md").read_text(encoding="utf-8")
        section = changelog_section(text, version)
        if section is None:
            return 1
        sys.stdout.write(section)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
