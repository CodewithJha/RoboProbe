#!/usr/bin/env python3
"""Summarize the nightly simulator's JUnit and episode measurements."""

from __future__ import annotations

import argparse
import json
import math
from pathlib import Path
from xml.etree import ElementTree


def _escape(cell: str) -> str:
    return cell.replace("|", r"\|").replace("\n", " ")


def _episode_factors(results: Path) -> list[tuple[str, float]]:
    factors = []
    for path in sorted(results.rglob("episode_done.json")):
        try:
            value = json.loads(path.read_text(encoding="utf-8"))["rtf_mean"]
        except (OSError, KeyError, ValueError, TypeError):
            continue
        if isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value):
            factors.append((path.parent.relative_to(results).as_posix(), value))
    return factors


def _record_factors(
    tree: ElementTree.ElementTree[ElementTree.Element[str]],
    report: Path,
    factors: list[tuple[str, float]],
) -> None:
    root = tree.getroot()
    suite = root if root.tag == "testsuite" else root.find("testsuite")
    if suite is None:
        return
    properties = suite.find("properties")
    if properties is None:
        properties = ElementTree.Element("properties")
        suite.insert(0, properties)
    saved = {item.get("name"): item for item in properties}
    for episode, factor in factors:
        name = f"rtf_mean.{episode}"
        item = saved.get(name)
        if item is None:
            item = ElementTree.SubElement(properties, "property", name=name)
        item.set("value", f"{factor:.6f}")
    temporary = report.with_suffix(".tmp")
    tree.write(temporary, encoding="utf-8", xml_declaration=True)
    temporary.replace(report)


def summarize(results: Path, *, annotate_junit: bool = False) -> tuple[str, bool]:
    """Format the test durations and real-time factors and indicate suite success."""
    report = results / "simulation.xml"
    if not report.is_file():
        return "## Gazebo simulation\n\nNo simulator test report was generated.\n", False
    try:
        tree = ElementTree.parse(report)  # noqa: S314 - local pytest output
    except (OSError, ElementTree.ParseError):
        return "## Gazebo simulation\n\nThe simulator test report was incomplete.\n", False
    lines = ["## Gazebo simulation", "", "| Test | Status | Duration (s) |", "|---|---|---:|"]
    counts = {"passed": 0, "failed": 0, "skipped": 0}
    for case in tree.findall(".//testcase"):
        status = "passed"
        if case.find("failure") is not None or case.find("error") is not None:
            status = "failed"
        elif case.find("skipped") is not None:
            status = "skipped"
        counts[status] += 1
        name = _escape(case.get("name", "unnamed"))
        lines.append(f"| {name} | {status} | {case.get('time', '—')} |")
    lines += ["", ", ".join(f"{count} {label}" for label, count in counts.items()), ""]
    if factors := _episode_factors(results):
        lines += ["| Episode | Mean RTF |", "|---|---:|"]
        lines.extend(f"| {_escape(name)} | {factor:.3f} |" for name, factor in factors)
        if annotate_junit:
            _record_factors(tree, report, factors)
    return "\n".join(lines) + "\n", counts["passed"] > 0 and counts["failed"] == 0


def main() -> int:
    """Write the Markdown summary and fail empty, all-skipped, or failed suites."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("results", type=Path)
    parser.add_argument("--annotate-junit", action="store_true")
    args = parser.parse_args()
    summary, success = summarize(args.results, annotate_junit=args.annotate_junit)
    print(summary, end="")
    return 0 if success else 1


if __name__ == "__main__":
    raise SystemExit(main())
