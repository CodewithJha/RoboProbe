#!/usr/bin/env python3
"""Fail if any dependency's licence is not on the allow-list (NFR-COST-001, doc 31 TM-10).

Inputs are the JSON reports of ``pip-licenses --format=json`` (backend) and
``pnpm licenses list --json`` (web). Licence strings may be SPDX expressions
(``MIT OR Apache-2.0``, ``(BSD-3-Clause AND Zlib)``, ``Apache-2.0 WITH LLVM-exception``) or
trove-classifier names joined by ``;`` (pip-licenses ``--from=mixed``), which are treated as
alternatives. A package passes when the expression is satisfiable using allowed licences only.

Standard library only. Exit status: 0 all allowed, 1 disallowed licence found, 2 usage/input error.
"""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections.abc import Iterable
from dataclasses import dataclass
from pathlib import Path

DEFAULT_ALLOWED_FILE = Path(__file__).with_name("allowed_licenses.txt")
OPEN_PAREN, CLOSE_PAREN = "(", ")"
TOKEN_PATTERN = re.compile(r"\(|\)|[^\s()]+")
CLASSIFIER_SEPARATOR = ";"

EXIT_OK = 0
EXIT_DISALLOWED = 1
EXIT_USAGE = 2


@dataclass(frozen=True, slots=True)
class PackageLicense:
    """One dependency and the licence string it declares."""

    ecosystem: str
    name: str
    version: str
    license: str


def load_allowed(path: Path) -> frozenset[str]:
    """Read the allow-list: one licence per line, ``#`` comments; matching is case-insensitive."""
    entries = (
        line.split("#", 1)[0].strip() for line in path.read_text(encoding="utf-8").splitlines()
    )
    return frozenset(entry.casefold() for entry in entries if entry)


class _Parser:
    """Recursive-descent evaluator for SPDX expressions: OR < AND < WITH, with parentheses."""

    def __init__(self, expression: str, allowed: frozenset[str]) -> None:
        self._tokens = TOKEN_PATTERN.findall(expression)
        self._pos = 0
        self._allowed = allowed

    def evaluate(self) -> bool:
        result = self._or()
        if self._pos != len(self._tokens):
            msg = f"unexpected token {self._tokens[self._pos]!r}"
            raise ValueError(msg)
        return result

    def _peek(self) -> str | None:
        return self._tokens[self._pos] if self._pos < len(self._tokens) else None

    def _take(self) -> str:
        token = self._peek()
        if token is None:
            msg = "unexpected end of expression"
            raise ValueError(msg)
        self._pos += 1
        return token

    def _keyword(self, word: str) -> bool:
        token = self._peek()
        if token is not None and token.upper() == word:
            self._pos += 1
            return True
        return False

    def _or(self) -> bool:
        result = self._and()
        while self._keyword("OR"):
            result = self._and() or result
        return result

    def _and(self) -> bool:
        result = self._with()
        while self._keyword("AND"):
            result = self._with() and result
        return result

    def _with(self) -> bool:
        result = self._atom()
        if self._keyword("WITH"):
            self._take()  # exceptions only grant extra permissions, never restrict
        return result

    def _atom(self) -> bool:
        token = self._take()
        if token == OPEN_PAREN:
            result = self._or()
            if self._take() != CLOSE_PAREN:
                msg = "missing ')'"
                raise ValueError(msg)
            return result
        return token.casefold() in self._allowed


def is_allowed(license_string: str, allowed: frozenset[str]) -> bool:
    """Whether ``license_string`` can be satisfied using only ``allowed`` licences."""
    alternatives = [part.strip() for part in license_string.split(CLASSIFIER_SEPARATOR)]
    for alternative in filter(None, alternatives):
        if alternative.casefold() in allowed:  # classifier names contain spaces/parentheses
            return True
        try:
            if _Parser(alternative, allowed).evaluate():
                return True
        except ValueError:
            continue
    return False


def read_pip_licenses(path: Path) -> list[PackageLicense]:
    """Parse ``pip-licenses --format=json`` output."""
    rows = json.loads(path.read_text(encoding="utf-8"))
    return [PackageLicense("python", row["Name"], row["Version"], row["License"]) for row in rows]


def read_pnpm_licenses(path: Path) -> list[PackageLicense]:
    """Parse ``pnpm licenses list --json`` output (licence -> packages)."""
    groups: dict[str, list[dict[str, object]]] = json.loads(path.read_text(encoding="utf-8"))
    packages: list[PackageLicense] = []
    for license_name, entries in groups.items():
        for entry in entries:
            versions = entry.get("versions")
            version = ",".join(map(str, versions)) if isinstance(versions, list) else ""
            packages.append(PackageLicense("node", str(entry["name"]), version, license_name))
    return packages


def find_disallowed(
    packages: Iterable[PackageLicense], allowed: frozenset[str]
) -> list[PackageLicense]:
    """Packages whose licence is not satisfiable from the allow-list, sorted for stable output."""
    bad = (pkg for pkg in packages if not is_allowed(pkg.license, allowed))
    return sorted(bad, key=lambda pkg: (pkg.ecosystem, pkg.name.casefold()))


def main(argv: list[str] | None = None) -> int:
    """CLI entry point."""
    parser = argparse.ArgumentParser(description="Check dependency licences against an allow-list.")
    parser.add_argument("--pip-licenses", type=Path, help="pip-licenses --format=json report")
    parser.add_argument("--pnpm-licenses", type=Path, help="pnpm licenses list --json report")
    parser.add_argument(
        "--allowed", type=Path, default=DEFAULT_ALLOWED_FILE, help="allow-list file"
    )
    args = parser.parse_args(argv)
    if args.pip_licenses is None and args.pnpm_licenses is None:
        parser.error("give at least one of --pip-licenses / --pnpm-licenses")

    try:
        allowed = load_allowed(args.allowed)
        packages = [
            *(read_pip_licenses(args.pip_licenses) if args.pip_licenses else []),
            *(read_pnpm_licenses(args.pnpm_licenses) if args.pnpm_licenses else []),
        ]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"licenses: error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    disallowed = find_disallowed(packages, allowed)
    for pkg in disallowed:
        print(
            f"licenses: {pkg.ecosystem} {pkg.name} {pkg.version}: {pkg.license!r} not allowed",
            file=sys.stderr,
        )
    if disallowed:
        print(
            f"licenses: add an OSI licence to {args.allowed} only after review (CONTRIBUTING.md)",
            file=sys.stderr,
        )
        return EXIT_DISALLOWED
    print(f"licenses: {len(packages)} package(s) OK")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
