#!/usr/bin/env python3
"""Check that every ADR file is listed in each ADR index, and that each index lists only real ADRs.

Indexes checked (doc 20 §1, ``docs.yml``):

* ``docs/adr/README.md`` — the ADR directory index;
* ``docs/15-tech-stack-and-adrs.md`` §2 — the index embedded in the tech-stack document.

For every index the check verifies that the set of linked ADR files equals the set of
``ADR-NNNN-*.md`` files on disk, and that the status column matches the ``Status`` field
of the ADR itself. Standard library only, so it runs before any project environment exists.

Exit status: 0 when consistent, 1 when a mismatch is found, 2 on usage or I/O errors.
"""

from __future__ import annotations

import argparse
import re
import sys
from dataclasses import dataclass
from pathlib import Path

ADR_FILE_PATTERN = re.compile(r"^ADR-(?P<number>\d{4})-[a-z0-9-]+\.md$")
ADR_LINK_PATTERN = re.compile(r"\[ADR-(?P<number>\d{4})\]\((?P<target>[^)#\s]+)\)")
STATUS_FIELD_PATTERN = re.compile(r"^\|\s*Status\s*\|\s*(?P<status>[^|]+?)\s*\|", re.MULTILINE)
HEADING_PATTERN = re.compile(r"^(?P<hashes>#{1,6})\s+(?P<title>.+?)\s*$")

DEFAULT_ADR_DIR = Path("docs/adr")
DEFAULT_INDEXES = (
    "docs/adr/README.md",
    "docs/15-tech-stack-and-adrs.md#ADR index",
)

EXIT_OK = 0
EXIT_MISMATCH = 1
EXIT_USAGE = 2


@dataclass(frozen=True, slots=True)
class IndexEntry:
    """One ADR row of an index table."""

    number: str
    target: Path
    status: str | None


@dataclass(frozen=True, slots=True)
class IndexSpec:
    """An index document, optionally restricted to the section titled like ``section``."""

    path: Path
    section: str | None

    @classmethod
    def parse(cls, raw: str) -> IndexSpec:
        """Parse ``path`` or ``path#section heading text``."""
        path, _, section = raw.partition("#")
        return cls(Path(path), section or None)

    def __str__(self) -> str:
        """Render as ``path (section)`` for messages."""
        return f"{self.path} ({self.section})" if self.section else str(self.path)


def read_adr_statuses(adr_dir: Path) -> dict[Path, str | None]:
    """Map each ADR file in ``adr_dir`` to the value of its ``Status`` field (None if absent)."""
    statuses: dict[Path, str | None] = {}
    for path in sorted(adr_dir.iterdir()):
        if ADR_FILE_PATTERN.match(path.name):
            match = STATUS_FIELD_PATTERN.search(path.read_text(encoding="utf-8"))
            statuses[path.resolve()] = match.group("status") if match else None
    return statuses


def extract_section(markdown: str, heading_text: str) -> str:
    """Return the body under the first heading whose title contains ``heading_text``.

    The body ends at the next heading of the same or a higher level.

    Raises:
        LookupError: if no heading contains ``heading_text``.
    """
    lines = markdown.splitlines()
    for start, line in enumerate(lines):
        heading = HEADING_PATTERN.match(line)
        if heading and heading_text.casefold() in heading.group("title").casefold():
            level = len(heading.group("hashes"))
            end = next(
                (
                    i
                    for i in range(start + 1, len(lines))
                    if (h := HEADING_PATTERN.match(lines[i])) and len(h.group("hashes")) <= level
                ),
                len(lines),
            )
            return "\n".join(lines[start + 1 : end])
    msg = f"no heading containing {heading_text!r}"
    raise LookupError(msg)


def parse_index(markdown: str, base_dir: Path) -> list[IndexEntry]:
    """Parse ADR rows (``| [ADR-NNNN](target) | title | status | ...``) from a Markdown table."""
    entries: list[IndexEntry] = []
    for line in markdown.splitlines():
        if not line.lstrip().startswith("|"):
            continue
        link = ADR_LINK_PATTERN.search(line)
        if link is None:
            continue
        cells = [cell.strip() for cell in line.strip().strip("|").split("|")]
        status_column = 2
        status = cells[status_column] if len(cells) > status_column else None
        entries.append(
            IndexEntry(link.group("number"), (base_dir / link.group("target")).resolve(), status)
        )
    return entries


def check_index(spec: IndexSpec, statuses: dict[Path, str | None], repo_root: Path) -> list[str]:
    """Return human-readable problems found in one index (empty list when consistent)."""
    path = repo_root / spec.path
    markdown = path.read_text(encoding="utf-8")
    if spec.section is not None:
        markdown = extract_section(markdown, spec.section)
    entries = parse_index(markdown, path.parent)

    problems: list[str] = []
    seen: set[Path] = set()
    for entry in entries:
        name = entry.target.name
        if entry.target in seen:
            problems.append(f"{spec}: ADR-{entry.number} is listed more than once")
        seen.add(entry.target)
        if entry.target not in statuses:
            problems.append(f"{spec}: ADR-{entry.number} links to missing file {name}")
            continue
        if not name.startswith(f"ADR-{entry.number}-"):
            problems.append(f"{spec}: link text ADR-{entry.number} does not match file {name}")
        actual = statuses[entry.target]
        if actual is not None and entry.status is not None and entry.status != actual:
            problems.append(
                f"{spec}: ADR-{entry.number} status {entry.status!r} != {actual!r} in {name}"
            )
    problems.extend(
        f"{spec}: {missing.name} is not listed" for missing in sorted(set(statuses) - seen)
    )
    return problems


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description=__doc__.splitlines()[0] if __doc__ else None)
    parser.add_argument(
        "--root", type=Path, default=Path.cwd(), help="repository root (default: cwd)"
    )
    parser.add_argument(
        "--adr-dir", type=Path, default=DEFAULT_ADR_DIR, help="ADR directory, relative to root"
    )
    parser.add_argument(
        "--index",
        action="append",
        dest="indexes",
        metavar="PATH[#SECTION]",
        help="index document, optionally limited to a section; repeatable (default: both)",
    )
    args = parser.parse_args(argv)
    root: Path = args.root.resolve()
    specs = [IndexSpec.parse(raw) for raw in (args.indexes or DEFAULT_INDEXES)]

    try:
        statuses = read_adr_statuses(root / args.adr_dir)
        problems = [problem for spec in specs for problem in check_index(spec, statuses, root)]
    except (OSError, LookupError) as exc:
        print(f"adr-index: error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    if not statuses:
        print(f"adr-index: error: no ADR files in {args.adr_dir}", file=sys.stderr)
        return EXIT_USAGE
    for problem in problems:
        print(f"adr-index: {problem}", file=sys.stderr)
    if problems:
        return EXIT_MISMATCH
    print(f"adr-index: {len(statuses)} ADR(s) consistent across {len(specs)} index(es)")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
