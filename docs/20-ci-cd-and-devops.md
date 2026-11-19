# 20 — CI/CD & DevOps

> Related: [ADR-0013](adr/ADR-0013-docker-compose-and-github-actions.md) · [18 Testing](18-testing-strategy-and-qa.md) · [29 Deployment](29-deployment-guide.md) · [33 Versioning & release](33-versioning-release-and-changelog-policy.md)
> Cost: GitHub Actions minutes and GHCR storage are free for public repositories. No paid services.

## 1. Workflows (`.github/workflows/`)

| Workflow | Trigger | Jobs | Target duration |
|----------|---------|------|-----------------|
| `ci.yml` | push, pull_request | `lint` (ruff, mypy, import-linter, ESLint, Prettier), `test-backend` (matrix ubuntu/macos; unit, property, contract), `test-integration` (Postgres 17 service), `benchmark-smoke`, `test-web` (Vitest), `build-web`, `openapi-check`, `config-docs-check`, `license-check`, `security` (pip-audit, pnpm audit, gitleaks) | ≤ 10 min |
| `docs.yml` | changes in `docs/**`, `*.md` | markdownlint, mermaid-cli render of every Mermaid block, lychee link check, ADR index check | ≤ 3 min |
| `images.yml` | push to `main`, tags | build `backend`, `web`, `gazebo` images (Buildx + GHA cache), Trivy scan, push to GHCR (`:sha`, `:main`, `:vX.Y.Z`), SBOM (Syft) attached | ≤ 25 min (gazebo cached) |
| `e2e.yml` | nightly 02:00 IST, manual | compose `core` up from built images, demo campaign, Playwright + axe | ≤ 20 min |
| `nightly-sim.yml` | nightly / manual (`workflow_dispatch`) | pull gazebo image, `pytest -m sim` with 1 worker, upload artefacts | ≤ 60 min (hosted runner CPU) |
| `benchmark-full.yml` | weekly, manual | EXP-02 analytic + reduced EXP-01 (10 seeds) → compare with baseline JSON, comment on regression | ≤ 45 min |
| `release.yml` | tag `v*` | verify CHANGELOG entry, build/push images, create GitHub Release with notes, report bundle | ≤ 30 min |

## 2. PR pipeline

```mermaid
flowchart LR
    P["Push / PR"] --> L["lint + typecheck"]
    P --> U["unit + property + contract"]
    P --> W["web unit + build"]
    P --> D["docs checks (if docs changed)"]
    L --> I["integration (Postgres service)"]
    U --> I
    I --> B["benchmark smoke"]
    W --> O["openapi + config-docs drift"]
    B --> G{"all green?"}
    O --> G
    D --> G
    G -->|"yes"| R["review + squash merge"]
    G -->|"no"| X["blocked"]
    R --> IM["images.yml on main"]
    IM --> N["nightly e2e + sim use main images"]
```

## 3. Branch protection (`main`)

Required checks (exact GitHub check names): `lint`, `test-backend (ubuntu-latest)`, `test-integration`, `test-web`, `build-web`, `openapi-check` (once T-084b adds it), `docs-check` (from `docs.yml`; only runs when Markdown changes). `test-backend (macos-latest)` runs on every PR but is advisory. Linear history, squash merge, no force pushes, conversation resolution required.

## 4. Caching & speed

`astral-sh/setup-uv` with cache keyed on `uv.lock`; `pnpm` store cache keyed on lockfile; Docker layer cache `type=gha`; Hypothesis database cached; tests parallelised with `pytest-xdist -n auto` for unit tiers.

## 5. Environments & configuration

| Env | Where | Config source |
|-----|-------|---------------|
| `ci` | GitHub runners | workflow `env:` + service containers; `ROBOPROBE_ENV=ci` |
| `local` | developer laptop | `.env` + `roboprobe.toml` |
| `lab` (optional) | spare machine / free-tier VM running remote workers | `.env.lab`, secrets via files, WireGuard/SSH tunnel to DB |

Secrets in CI: only `GITHUB_TOKEN` (GHCR push). No external secret is needed.

## 6. Release & deployment flow

1. Merge to `main` → images `:main` and `:sha-<7>` pushed.
2. Release: bump version (33), update `CHANGELOG.md`, tag `vX.Y.Z` → `release.yml` publishes images `:vX.Y.Z` and a GitHub Release.
3. Deploy on a machine: `ROBOPROBE_IMAGE_TAG=vX.Y.Z make up` (migrations run automatically via the `migrate` one-shot service) — see 29.
4. Rollback: set previous tag and `make up`; DB migrations are backward-compatible for one minor version (expand/contract pattern, 33 §5).

## 7. Dependency management

Dependabot weekly for `uv`, `npm`, `github-actions`, `docker`; grouped minor/patch updates; major updates as separate PRs with a changelog review. ROS/Gazebo base images pinned by digest and updated monthly via a manual PR after `nightly-sim` passes.

## 8. Observability of CI

Test reports as JUnit XML uploaded and summarised in the job summary; coverage uploaded as artefact and summarised (no paid coverage service required; Codecov free tier optional).
