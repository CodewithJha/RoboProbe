#!/usr/bin/env python3
"""Fail on known vulnerabilities at or above a severity threshold (NFR-SEC-002, doc 31 TM-10).

Inputs are the JSON reports of ``pip-audit --format=json`` (backend) and ``pnpm audit --json``
(web). pnpm reports a severity per advisory. pip-audit does not, so each Python finding is
looked up in the OSV database (GHSA ``database_specific.severity``, following GHSA aliases).
A finding whose severity cannot be determined is treated as ``critical``, so nothing slips
through unreviewed.

Accepted risks live in an ignore file. Each line is ``<ID>  # <justification>``, where the ID is
the advisory ID or any alias (CVE, GHSA, PYSEC). Every entry must carry a justification.

Standard library only. Exit status: 0 clean, 1 blocking findings, 2 usage/input error.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import urllib.request
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path

SEVERITIES = ("low", "moderate", "high", "critical")
"""Ascending order. GHSA ``MODERATE`` and CVSS ``medium`` both map to ``moderate``."""
SEVERITY_ALIASES = {"medium": "moderate", "info": "low"}
UNKNOWN_SEVERITY = "critical"
DEFAULT_THRESHOLD = "high"
DEFAULT_IGNORE_FILE = Path(__file__).with_name("audit_ignore.txt")
OSV_API_ENV = "OSV_API_URL"
DEFAULT_OSV_API = "https://api.osv.dev/v1"
OSV_TIMEOUT_S_ENV = "OSV_TIMEOUT_S"
DEFAULT_OSV_TIMEOUT_S = 20.0

EXIT_OK = 0
EXIT_BLOCKING = 1
EXIT_USAGE = 2

Fetch = Callable[[str], Mapping[str, object]]
"""Returns the OSV record for a vulnerability ID."""


@dataclass(frozen=True, slots=True)
class Finding:
    """One vulnerable package version."""

    ecosystem: str
    package: str
    version: str
    advisory: str
    aliases: frozenset[str] = field(default_factory=frozenset)
    severity: str | None = None

    @property
    def ids(self) -> frozenset[str]:
        """Advisory ID plus all aliases."""
        return self.aliases | {self.advisory}


def normalise_severity(raw: object) -> str | None:
    """Map a severity label to one of :data:`SEVERITIES` (None if unrecognised)."""
    if not isinstance(raw, str):
        return None
    label = SEVERITY_ALIASES.get(raw.strip().casefold(), raw.strip().casefold())
    return label if label in SEVERITIES else None


def load_ignore_file(path: Path) -> dict[str, str]:
    """Return ``{id: justification}``. Raises ValueError on entries without a justification."""
    if not path.exists():
        return {}
    ignored: dict[str, str] = {}
    for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        entry, _, comment = line.partition("#")
        if not entry.strip():
            continue
        if not comment.strip():
            msg = f"{path}:{number}: {entry.strip()} needs a '# justification'"
            raise ValueError(msg)
        ignored[entry.strip()] = comment.strip()
    return ignored


def read_pip_audit(path: Path) -> list[Finding]:
    """Parse ``pip-audit --format=json`` output."""
    report = json.loads(path.read_text(encoding="utf-8"))
    return [
        Finding(
            "python", dep["name"], dep["version"], vuln["id"], frozenset(vuln.get("aliases", []))
        )
        for dep in report["dependencies"]
        for vuln in dep.get("vulns", [])
    ]


def read_pnpm_audit(path: Path) -> list[Finding]:
    """Parse ``pnpm audit --json`` output (npm v6 advisory format)."""
    report = json.loads(path.read_text(encoding="utf-8"))
    if "advisories" not in report or "metadata" not in report:
        # pnpm prints {"error": ...} on registry/network failures; never treat that as clean.
        msg = f"{path}: not a pnpm audit report: {str(report)[:200]}"
        raise ValueError(msg)
    findings: list[Finding] = []
    for key, advisory in report["advisories"].items():
        ghsa = advisory.get("github_advisory_id")
        aliases = frozenset(filter(None, [*advisory.get("cves", []), ghsa, str(key)]))
        versions = sorted({str(f.get("version")) for f in advisory.get("findings", [])})
        findings.append(
            Finding(
                "node",
                advisory["module_name"],
                ",".join(versions),
                ghsa or str(key),
                aliases,
                normalise_severity(advisory.get("severity")),
            ),
        )
    return findings


def osv_fetcher(base_url: str, timeout_s: float) -> Fetch:
    """Build a fetcher for ``GET {base_url}/vulns/{id}``."""

    def fetch(vuln_id: str) -> Mapping[str, object]:
        url = f"{base_url.rstrip('/')}/vulns/{vuln_id}"
        with urllib.request.urlopen(url, timeout=timeout_s) as response:  # noqa: S310 - https URL from config
            record: Mapping[str, object] = json.load(response)
        return record

    return fetch


def osv_severity(finding: Finding, fetch: Fetch) -> str | None:
    """Severity from GHSA ``database_specific.severity`` of the finding, its aliases, or theirs."""
    queue = sorted(finding.ids, key=lambda vuln_id: not vuln_id.startswith("GHSA-"))
    seen: set[str] = set()
    while queue:
        vuln_id = queue.pop(0)
        if vuln_id in seen:
            continue
        seen.add(vuln_id)
        try:
            record = fetch(vuln_id)
        except OSError:
            continue
        specific = record.get("database_specific")
        raw = specific.get("severity") if isinstance(specific, Mapping) else None
        severity = normalise_severity(raw)
        if severity is not None:
            return severity
        aliases = record.get("aliases")
        if isinstance(aliases, list):
            queue.extend(str(alias) for alias in aliases if str(alias).startswith("GHSA-"))
    return None


def classify(
    findings: Iterable[Finding],
    ignored: Mapping[str, str],
    threshold: str,
    fetch: Fetch,
) -> tuple[list[Finding], list[Finding]]:
    """Split findings into (blocking, accepted). Severity is resolved via ``fetch`` when missing."""
    floor = SEVERITIES.index(threshold)
    blocking: list[Finding] = []
    accepted: list[Finding] = []
    for finding in findings:
        if finding.ids & ignored.keys():
            accepted.append(finding)
            continue
        severity = finding.severity or osv_severity(finding, fetch) or UNKNOWN_SEVERITY
        resolved = Finding(
            finding.ecosystem,
            finding.package,
            finding.version,
            finding.advisory,
            finding.aliases,
            severity,
        )
        (blocking if SEVERITIES.index(severity) >= floor else accepted).append(resolved)
    return blocking, accepted


def _describe(finding: Finding) -> str:
    return (
        f"{finding.ecosystem} {finding.package} {finding.version}: {finding.advisory} "
        f"({finding.severity or 'ignored'})"
    )


def main(argv: list[str] | None = None, fetch: Fetch | None = None) -> int:
    """CLI entry point. ``fetch`` overrides the OSV lookup (tests)."""
    parser = argparse.ArgumentParser(description="Gate dependency audit reports by severity.")
    parser.add_argument("--pip-audit", type=Path, help="pip-audit --format=json report")
    parser.add_argument("--pnpm-audit", type=Path, help="pnpm audit --json report")
    parser.add_argument("--ignore-file", type=Path, default=DEFAULT_IGNORE_FILE)
    parser.add_argument("--fail-on", choices=SEVERITIES, default=DEFAULT_THRESHOLD)
    args = parser.parse_args(argv)
    if args.pip_audit is None and args.pnpm_audit is None:
        parser.error("give at least one of --pip-audit / --pnpm-audit")

    if fetch is None:
        timeout_s = float(os.environ.get(OSV_TIMEOUT_S_ENV, DEFAULT_OSV_TIMEOUT_S))
        fetch = osv_fetcher(os.environ.get(OSV_API_ENV, DEFAULT_OSV_API), timeout_s)
    try:
        ignored = load_ignore_file(args.ignore_file)
        findings = [
            *(read_pip_audit(args.pip_audit) if args.pip_audit else []),
            *(read_pnpm_audit(args.pnpm_audit) if args.pnpm_audit else []),
        ]
    except (OSError, ValueError, KeyError, TypeError) as exc:
        print(f"audit: error: {exc}", file=sys.stderr)
        return EXIT_USAGE

    blocking, accepted = classify(findings, ignored, args.fail_on, fetch)
    for finding in accepted:
        print(f"audit: accepted {_describe(finding)}")
    for finding in blocking:
        print(f"audit: BLOCKING {_describe(finding)}", file=sys.stderr)
    if blocking:
        print(f"audit: fix, upgrade, or justify in {args.ignore_file}", file=sys.stderr)
        return EXIT_BLOCKING
    print(f"audit: no {args.fail_on}+ vulnerabilities ({len(findings)} finding(s) total)")
    return EXIT_OK


if __name__ == "__main__":
    sys.exit(main())
