#!/usr/bin/env python3
"""Audit the release traceability matrix against checked-in evidence and completed issues.

Exit status is 0 for complete evidence, 1 for gaps, or 2 for invalid inputs. Test IDs
and the import-linter CI gate are checked in source without running ROS or a browser.
"""

from __future__ import annotations

import argparse
import ast
import json
import re
import subprocess
import sys
import tomllib
from pathlib import Path

REPOSITORY = "CodewithJha/RoboProbe"
REPO = Path(__file__).resolve().parents[1]
SRS_PATH = Path("docs/02-software-requirements-specification.md")
MATRIX_PATH = Path("docs/28-traceability-matrix.md")
BEGIN = "<!-- BEGIN REQUIREMENT EVIDENCE -->"
END = "<!-- END REQUIREMENT EVIDENCE -->"
_GH_TIMEOUT_S = 45
_IMPORT_LINT_GATE = "ci:.github/workflows/ci.yml::lint::make lint"

_REQUIREMENT = re.compile(r"^(?:- \*\*(FR-[A-Z]+-\d{3})|\| (NFR-[A-Z]+-\d{3})) \[", re.MULTILINE)
_ROW = re.compile(
    r"^\|[ \t]*((?:FR|NFR)-[A-Z]+-\d{3})[ \t]*\|[ \t]*([^|\r\n]*)\|[ \t]*([^|\r\n]*)\|[ \t]*$",
    re.MULTILINE,
)
_NODE = re.compile(r"`([^`]+)`")
_ISSUE = re.compile(rf"^https://github\.com/{REPOSITORY}/issues/[1-9]\d*$", re.IGNORECASE)
_LINK = re.compile(r"\]\((https://github\.com/[^\s)]+)\)")
_TS_TEST = re.compile(r"^[^\S\r\n]*(?:test|it)\(\s*(['\"])([^\r\n]*?)\1\s*,", re.MULTILINE)
_TEST_DIRECTORIES = (
    Path("backend/tests"),
    Path("ros_ws"),
    Path("scripts/tests"),
    Path("web"),
)


def requirement_ids(text: str) -> set[str]:
    """Read canonical FR bullet and NFR table IDs from the SRS."""
    return {functional or nonfunctional for functional, nonfunctional in _REQUIREMENT.findall(text)}


def _python_test_exists(source: str, names: list[str]) -> bool:
    scope: ast.Module | ast.ClassDef = ast.parse(source)
    for name in names[:-1]:
        classes = [node for node in scope.body if isinstance(node, ast.ClassDef)]
        child = next((node for node in classes if node.name == name), None)
        if child is None:
            return False
        if not name.startswith("Test") and all(
            ast.unparse(base) not in {"TestCase", "unittest.TestCase"} for base in child.bases
        ):
            return False
        scope = child
    return names[-1].startswith("test_") and any(
        isinstance(node, ast.FunctionDef | ast.AsyncFunctionDef) and node.name == names[-1]
        for node in scope.body
    )


def test_node_exists(root: Path, node: str) -> bool:
    """Resolve a pytest, Vitest or Playwright node against checked-in test source."""
    file, *names = node.split("::")
    relative = Path(file)
    if not names or relative.is_absolute():
        return False
    try:
        base = root.resolve()
        path = (base / relative).resolve()
        if not any(path.is_relative_to(base / directory) for directory in _TEST_DIRECTORIES):
            return False
        source = path.read_text(encoding="utf-8")
        if path.suffix == ".py" and path.name.startswith("test_"):
            return _python_test_exists(source, names)
        if path.name.endswith((".test.ts", ".test.tsx", ".spec.ts")) and len(names) == 1:
            source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
            return any(title == names[0] for _, title in _TS_TEST.findall(source))
    except (OSError, SyntaxError, UnicodeError):
        return False
    return False


def _indented_block(source: str, heading: str) -> str:
    """Read a block at its exact indentation in the checked-in workflow or Makefile."""
    match = re.search(rf"(?m)^{re.escape(heading)}[ \t]*(?:#[^\n]*)?\n", source)
    if match is None:
        return ""
    indent = len(heading) - len(heading.lstrip())
    return re.split(
        rf"(?m)^(?=[ \t]{{0,{indent}}}[^ \t\r\n#])",
        source[match.end() :],
        maxsplit=1,
    )[0]


def _workflow_runs_required_import_lint(source: str) -> bool:
    """Check the lint job's ordinary, blocking invocation of the Make lint recipe."""
    if not re.search(r"(?m)^  pull_request:[ \t]*$", _indented_block(source, "on:")):
        return False
    job = _indented_block(_indented_block(source, "jobs:"), "  lint:")
    nonblocking = r"(?:if|continue-on-error):"
    if re.search(rf"(?m)^    {nonblocking}", job):
        return False
    steps = _indented_block(job, "    steps:")
    return any(
        re.search(r"(?m)^(?: {8})?run: make lint[ \t]*(?:#[^\n]*)?$", step)
        and not re.search(rf"(?m)^(?: {{8}})?{nonblocking}", step)
        for step in re.split(r"(?m)^      - ", steps)[1:]
    )


def _import_lint_gate_exists(root: Path) -> bool:
    """Resolve the single architecture gate through CI, Make, and Import Linter config."""
    root = root.resolve()
    workflow = root / ".github/workflows/ci.yml"
    makefile = root / "Makefile"
    tool_config = root / "backend/pyproject.toml"
    try:
        if any(path.resolve() != path for path in (workflow, makefile, tool_config)):
            return False
        if not _workflow_runs_required_import_lint(workflow.read_text(encoding="utf-8")):
            return False
        make = makefile.read_text(encoding="utf-8")
        if (
            "\t$(UV_RUN) lint-imports" not in _indented_block(make, "lint:").splitlines()
            or not re.search(r"(?m)^BACKEND_DIR[ \t]*\?= backend[ \t]*$", make)
            or not re.search(
                r"(?m)^UV_RUN[ \t]*:= \$\(UV\) run --directory \$\(BACKEND_DIR\)[ \t]*$",
                make,
            )
        ):
            return False
        config = tomllib.loads(tool_config.read_text(encoding="utf-8"))
        import_linter = config["tool"]["importlinter"]
        contracts = {contract["id"]: contract for contract in import_linter["contracts"]}
        layers = contracts["layers"]
        domain = contracts["domain-independence"]
        return bool(
            import_linter.get("root_packages") == ["roboprobe"]
            and layers.get("type") == "layers"
            and layers.get("layers")
            and domain.get("type") == "forbidden"
            and domain.get("source_modules")
            and domain.get("forbidden_modules")
            and domain.get("allow_indirect_imports") is False
        )
    except (KeyError, OSError, TypeError, ValueError):
        return False


def _evidence_exists(root: Path, requirement: str, reference: str) -> bool:
    if reference == _IMPORT_LINT_GATE:
        return requirement == "NFR-EXT-002" and _import_lint_gate_exists(root)
    return test_node_exists(root, reference)


def _matrix_rows(text: str) -> list[tuple[str, str, str]]:
    if text.count(BEGIN) != 1 or text.count(END) != 1 or text.find(BEGIN) > text.find(END):
        msg = "traceability matrix must contain one bounded requirement evidence table"
        raise ValueError(msg)
    table = text.split(BEGIN, 1)[1].split(END, 1)[0]
    rows = _ROW.findall(table)
    if not rows:
        msg = "traceability evidence table contains no requirement rows"
        raise ValueError(msg)
    return rows


def audit(root: Path, closed_issues: set[str]) -> tuple[int, list[str]]:
    """Report missing, stale and duplicate evidence for every declared requirement."""
    expected = requirement_ids((root / SRS_PATH).read_text(encoding="utf-8"))
    if not expected:
        msg = "the SRS contains no requirement declarations"
        raise ValueError(msg)
    rows = _matrix_rows((root / MATRIX_PATH).read_text(encoding="utf-8"))
    seen: set[str] = set()
    problems: list[str] = []
    for identifier, test_cell, issue_cell in rows:
        if identifier in seen:
            problems.append(f"{identifier} has duplicate evidence rows")
            continue
        seen.add(identifier)
        if identifier not in expected:
            problems.append(f"{identifier} is not declared in the SRS")
            continue
        test_ids = _NODE.findall(test_cell)
        stale_nodes = [node for node in test_ids if not _evidence_exists(root, identifier, node)]
        if stale_nodes or not test_ids:
            detail = f" ({', '.join(stale_nodes)})" if stale_nodes else ""
            kind = "test node or accepted CI gate" if identifier == "NFR-EXT-002" else "test node"
            problems.append(f"{identifier} has no existing {kind} for listed evidence{detail}")
        issue_urls = _LINK.findall(issue_cell)
        invalid_urls = [url for url in issue_urls if url.lower() not in closed_issues]
        if invalid_urls or not issue_urls:
            detail = f" ({', '.join(invalid_urls)})" if invalid_urls else ""
            problems.append(
                f"{identifier} has no verified closed GitHub issue for evidence{detail}"
            )
    problems.extend(f"{identifier} has no evidence row" for identifier in sorted(expected - seen))
    return len(expected), problems


def _closed_issues(root: Path, snapshot: Path | None) -> set[str]:
    if snapshot is None:
        command = [
            "gh",
            "issue",
            "list",
            "--repo",
            REPOSITORY,
            "--state",
            "closed",
            "--limit",
            "1000",
            "--json",
            "url,stateReason",
        ]
        result = subprocess.run(  # noqa: S603 - fixed GitHub CLI command
            command,
            cwd=root,
            capture_output=True,
            text=True,
            check=True,
            timeout=_GH_TIMEOUT_S,
        )
        source = result.stdout
    else:
        source = snapshot.read_text(encoding="utf-8")
    rows = json.loads(source)
    if not isinstance(rows, list) or not all(
        isinstance(row, dict) and isinstance(row.get("url"), str) and _ISSUE.fullmatch(row["url"])
        for row in rows
    ):
        msg = "invalid closed GitHub issue snapshot; expected the output of gh issue list"
        raise ValueError(msg)
    return {row["url"].lower() for row in rows if row.get("stateReason") == "COMPLETED"}


def main(argv: list[str] | None = None) -> int:
    """Run the strict audit, fetching current closed issue URLs by default."""
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=REPO)
    parser.add_argument(
        "--closed-issues",
        type=Path,
        help="Read a closed GitHub issue snapshot containing url and stateReason.",
    )
    args = parser.parse_args(argv)
    try:
        total, problems = audit(args.root, _closed_issues(args.root, args.closed_issues))
    except subprocess.SubprocessError:
        print(
            "Cannot query closed GitHub issues. Authenticate gh or pass --closed-issues.",
            file=sys.stderr,
        )
        return 2
    except (OSError, ValueError) as exc:
        print(f"Cannot check traceability: {exc}", file=sys.stderr)
        return 2
    if problems:
        print(
            f"Traceability has {len(problems)} evidence gaps across {total} requirements.",
            file=sys.stderr,
        )
        for problem in problems:
            print(problem, file=sys.stderr)
        return 1
    print(f"All {total} requirements have checked-in verification and a completed GitHub issue.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
