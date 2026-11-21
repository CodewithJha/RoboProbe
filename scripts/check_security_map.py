#!/usr/bin/env python3
"""Fail when a doc 31 threat has no row in the security-test map (T-109, NFR-SEC-003).

Reads the STRIDE table in ``docs/31-threat-model.md`` and ``docs/evidence/security-tests.md``.
Every ``TM-xx`` row needs a map entry whose status is ``pass`` or ``N/A``.

Exit status: 0 when the map is complete, 1 when a threat is missing or malformed.
"""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

_THREAT_ROW = re.compile(r"^\|\s*(TM-\d+)\s*\|")
_STATUSES = frozenset({"pass", "N/A"})
_REPO = Path(__file__).resolve().parents[1]


def threat_ids(threat_model: str) -> list[str]:
    """Return ``TM-xx`` ids in table order from the threat-model markdown."""
    found: list[str] = []
    for line in threat_model.splitlines():
        match = _THREAT_ROW.match(line)
        if match is not None:
            found.append(match.group(1))
    return found


def mapped_threats(evidence: str) -> dict[str, str]:
    """Return ``TM-xx`` → status from the evidence table."""
    mapped: dict[str, str] = {}
    for line in evidence.splitlines():
        match = _THREAT_ROW.match(line)
        if match is None:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        if len(cells) < 3:  # noqa: PLR2004 - threat, test, status
            continue
        mapped[match.group(1)] = cells[2]
    return mapped


def gaps(threat_model: str, evidence: str) -> list[str]:
    """Describe threat ids that lack a ``pass`` or ``N/A`` evidence row."""
    mapped = mapped_threats(evidence)
    problems: list[str] = []
    for threat_id in threat_ids(threat_model):
        status = mapped.get(threat_id)
        if status is None:
            problems.append(f"{threat_id} has no row in the security-test map")
        elif status not in _STATUSES:
            problems.append(f"{threat_id} status {status!r} is not pass or N/A")
    return problems


def main(argv: list[str] | None = None) -> int:
    """Check the map and print one problem per line."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--threats",
        type=Path,
        default=_REPO / "docs/31-threat-model.md",
    )
    parser.add_argument(
        "--evidence",
        type=Path,
        default=_REPO / "docs/evidence/security-tests.md",
    )
    args = parser.parse_args(argv)
    problems = gaps(
        args.threats.read_text(encoding="utf-8"), args.evidence.read_text(encoding="utf-8")
    )
    for problem in problems:
        print(problem, file=sys.stderr)
    return 1 if problems else 0


if __name__ == "__main__":
    raise SystemExit(main())
