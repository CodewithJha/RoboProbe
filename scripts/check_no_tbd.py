"""Fail if task/config YAML files still contain ``TBD_Tnnn`` placeholders (T-027).

Usage (from the repository root)::

    uv run --directory backend python ../scripts/check_no_tbd.py [--strict] [PATH ...]

PATH defaults to ``tasks`` and ``configs``; directories are searched for ``*.yaml``/``*.yml``.
With ``--strict`` (release builds), files that list ``provisional`` values fail too.
Exit status: 0 clean, 1 findings, 2 unreadable or invalid YAML.
"""

from __future__ import annotations

import argparse
import sys
from collections.abc import Iterator
from pathlib import Path

from roboprobe.core.errors import RoboProbeError
from roboprobe.scenario._documents import load_yaml_document
from roboprobe.scenario.task import find_placeholders

DEFAULT_PATHS = ("tasks", "configs")
YAML_SUFFIXES = (".yaml", ".yml")
EXIT_FINDINGS = 1
EXIT_UNREADABLE = 2


def iter_yaml_files(paths: list[Path]) -> Iterator[Path]:
    """Yield YAML files under ``paths`` (files are yielded as given), sorted per directory."""
    for path in paths:
        if path.is_dir():
            yield from sorted(p for p in path.rglob("*") if p.suffix in YAML_SUFFIXES)
        elif path.is_file():
            yield path


def check(paths: list[Path], *, strict: bool) -> tuple[list[str], list[str]]:
    """Return ``(findings, unreadable)`` messages for the given files and directories."""
    findings: list[str] = []
    unreadable: list[str] = []
    for file in iter_yaml_files(paths):
        try:
            document = load_yaml_document(file.read_bytes(), source=str(file))
        except (OSError, RoboProbeError) as exc:
            unreadable.append(f"{file}: {exc}")
            continue
        findings.extend(
            f"{file}:{ptr}: placeholder {value}" for ptr, value in find_placeholders(document)
        )
        if strict and isinstance(document, dict) and document.get("provisional"):
            findings.append(f"{file}: provisional values {document['provisional']}")
    return findings, unreadable


def main(argv: list[str] | None = None) -> int:
    """CLI entry point; returns the process exit status."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    parser.add_argument("paths", nargs="*", type=Path, default=[Path(p) for p in DEFAULT_PATHS])
    parser.add_argument("--strict", action="store_true", help="also fail on provisional values")
    args = parser.parse_args(argv)
    findings, unreadable = check(args.paths, strict=args.strict)
    for line in [*unreadable, *findings]:
        print(line, file=sys.stderr)
    if unreadable:
        return EXIT_UNREADABLE
    return EXIT_FINDINGS if findings else 0


if __name__ == "__main__":
    sys.exit(main())
