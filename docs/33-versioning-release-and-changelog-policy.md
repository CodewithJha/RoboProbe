# 33 — Versioning, Release & Changelog Policy

> Related: [20 CI/CD](20-ci-cd-and-devops.md) · [12 §1 API versioning](12-api-specification.md#1-conventions) · [11 §8 Migrations](11-data-model-and-database.md#8-migrations--versioning)

## 1. What is versioned, and how

| Artefact | Scheme | Where | Breaking change ⇒ |
|----------|--------|-------|-------------------|
| RoboProbe product (Python package, images, web) | **SemVer 2.0.0** `MAJOR.MINOR.PATCH` (pre-1.0: `0.MINOR.PATCH`, minor may break) | `backend/pyproject.toml`, git tag `vX.Y.Z`, image tags | MAJOR bump |
| REST API | URI major `/api/v1`; additive within major | OpenAPI `info.version` = product version | `/api/v2` + deprecation window |
| DB schema | Alembic revision chain | `backend/migrations/versions` | expand/contract over ≥ 1 minor |
| Scenario space files | `schema_version` (int) in YAML + JSON Schema `$id` | `schemas/` | new `schema_version`, upgrader `roboprobe space upgrade` |
| Scenario space content | `space_version` = content hash | DB `scenario_spaces.version` | automatic (new hash) |
| Trace files | `trace_schema_version` (Parquet metadata) | 11 §6.2 | reader upcaster |
| Manifests | `manifest_schema_version` | 21 §4 | reader upcaster |
| Analysis report | `analysis_schema_version` | 09 §7 | reader upcaster |
| Oracle semantics | `oracle_set_version` (e.g. `oracles-1`) stored per campaign | `roboprobe.oracles.__version__` | bump when any formula/default changes; results compared only within the same version |
| Strategy semantics | `strategy_version` per strategy class (e.g. `S-PROBE@1`) | strategy `version: ClassVar[int]` | bump when behaviour changes for the same seed |
| kinematic2d model | `k2d_model_version` | `configs/backends/kinematic2d_v1.yaml` | new file version; reference set regenerated |
| Docs | doc set version in 00 | 00 header | minor for additions, major for restructures |
| ROS package `roboprobe_ros` | `package.xml` version = product version | | with product |

## 2. Release cadence & process

- Pre-1.0: a minor release at each milestone exit (M1 → `0.1.0`, …, M10 → `0.10.0`), `1.0.0` at M11.
- Patch releases for bug fixes any time.

Release checklist:

1. `main` green including nightly e2e/sim of the release candidate commit.
2. Move CHANGELOG `Unreleased` → `## [X.Y.Z] - YYYY-MM-DD`; verify categories.
3. Bump versions (`uv version`, `package.json`, `package.xml`) in one `chore(release): vX.Y.Z` commit.
4. Tag `vX.Y.Z` (annotated) → `release.yml` builds/pushes images, creates GitHub Release with CHANGELOG section, SBOMs, and the demo report.
5. Verify deployment from the tag on a clean machine (29 §10) for MINOR/MAJOR.
6. Update 00 doc version if docs changed materially.

The release workflow runs the published-image demo using the exact release tag after the
images are available. It verifies the demo export and the backend, web, and Gazebo SPDX
documents from that workflow run before attaching the four files to the release.

## 3. CHANGELOG format

`CHANGELOG.md` follows **Keep a Changelog 1.1.0**: sections `Added`, `Changed`, `Deprecated`, `Removed`, `Fixed`, `Security` under `[Unreleased]` and each version. Entries are user-facing, reference task/issue ids, and call out behaviour changes of oracles/strategies explicitly (they affect result comparability).

## 4. Deprecation policy

- API fields/endpoints: mark `deprecated: true` in OpenAPI, send `Deprecation` and `Sunset` headers, keep for ≥ 2 minor releases.
- Config keys: old key accepted with a warning for ≥ 2 minor releases (alias in settings), then removed in next MAJOR.
- CLI flags: same as config keys.

## 5. Database migration policy (expand/contract)

1. **Expand**: add new columns/tables (nullable or defaulted); code writes both old and new.
2. **Migrate**: backfill in a separate, idempotent migration or job.
3. **Contract**: remove old columns only in a later minor release once no released version reads them.
Every migration has `downgrade()` for dev; production rollback = image rollback + compatible schema (no downgrade needed thanks to expand/contract).

## 6. Result comparability rule

Experiment comparisons are valid only between campaigns sharing `space_version`, `oracle_set_version`, `sut_profile.config_hash`, backend version and `k2d_model_version`. The experiment runner enforces this and the report prints these versions.
