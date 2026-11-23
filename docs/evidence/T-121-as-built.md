# T-121 as-built documentation refresh

RoboProbe **v1.0.0** — evidence for RC-7 and task T-121 (minimal ponytail pass).

## Automated checks (this commit)

| Check | Result | Notes |
|-------|--------|-------|
| `make config-docs-check` | PASS | Generated 27 / `.env.example` match settings models |
| `scripts/check_traceability.py` | **GAPS** (12) | Mostly linked; NFR evidence gaps e.g. NFR-USE-001 → #213 open |
| `make openapi` + committed `api/openapi.json` | PASS | URI `/api/v1`; snapshot in repo |
| ADR index (`scripts/check_adr_index.py`) | PASS | 16 ADRs consistent |
| markdownlint + mermaid (docs.yml) | PASS | Local `make docs-check` minus lychee (no installer in agent VM) |
| CHANGELOG `[1.0.0]` | PASS | Consolidated from `Unreleased` for T-123 |

## As-built anchors (source of truth for interfaces)

| Area | Canonical artefact |
|------|-------------------|
| REST API | [`api/openapi.json`](../../api/openapi.json) |
| Settings / config keys | [`docs/27-configuration-reference.md`](../27-configuration-reference.md) (generated) |
| Dashboard routes | [`web/src/app/router.tsx`](../../web/src/app/router.tsx) |
| Compose profiles | [`docker/compose.yaml`](../../docker/compose.yaml) |

## Honest gaps (non-blocking for v1.0.0 tag)

- Per-doc prose refresh across 04–13 is **not** line-by-line re-audited in this PR; drift is guarded by the checks above.
- External link crawl (lychee) was not run in the cloud agent environment.
- EXP-04 Gazebo video / full SC-4 compute and EXP-05/06 MET numbers remain **PENDING** on owner hardware (see `docs/evidence/EXP-04.md`, `EXP-05.md`, `EXP-06.md`, `deviations.md`).
- No ADR supersession edits in this pass — accepted ADRs unchanged since M0.

## Go / no-go (doc 26 §9) — documentation slice

| RC | Status | Evidence |
|----|--------|----------|
| RC-7 Docs as-built; CHANGELOG; ADRs current | **PASS** (with gaps above) | This file + CHANGELOG `[1.0.0]` |
