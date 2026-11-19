# AGENTS.md — Instructions for AI coding agents

You are implementing **RoboProbe** from the specification in `docs/`. The docs are the source of truth.

## 1. Before you write any code

1. Read, in order: `docs/00-index.md` → `01` → `26` (PRD) → `02` (SRS) → `04` → `34` → `16` → `18` → `32`.
2. Pick **one** task `T-NNN` from `docs/22-roadmap-and-implementation-plan.md` whose dependencies are Done and which satisfies the Definition of Ready (`docs/32` §2).
3. Read every document section the task links to. Copy interface signatures exactly from `docs/05` / `docs/12`.
4. If something is ambiguous or contradictory, do **not** guess silently: choose the most conservative interpretation, note it in the PR description under "Assumptions", and propose a docs fix in the same PR.

## 2. Build order (milestones)

M1 Foundation → Storage + M2 Scenario/kinematic2d → M3 Oracles/Runner → M4 Baselines/Metrics → M5 Intelligent selection → M6 Analysis/Risk → M7 API → M8 Dashboard → M9 Gazebo (spike T-090 early) → M10 Evaluation → M11 Release.

## 3. Non-negotiable rules

- **Architecture:** respect the layers and ports (`docs/16` §2, `docs/34`). Domain packages never import `store`, `backends`, `api`, `fastapi`, `sqlalchemy`, `rclpy`. Wire concrete classes only in `roboprobe.bootstrap`.
- **No hard-coded values:** every threshold, timeout, path, URL, port, hyper-parameter or secret is a typed settings/params field documented in `docs/27`. Only mathematical constants may be literals.
- **Determinism:** inject `np.random.Generator`/seeds and a `Clock`; never use global RNG or `time.time()` in domain code.
- **Typing & style:** Python 3.12, `mypy --strict`, ruff (config in `backend/pyproject.toml`), Google docstrings with `Implements: <IDs>`; TypeScript strict.
- **Tests first:** write failing tests, then code. Randomised algorithms are tested over multiple seeds with thresholds from config.
- **IDs are canonical:** use `M1–M8`, `P1–P8`, `S-*`, `F-*`, `O-*`, `MET-*` exactly as in the docs.
- **Free & open source only.** Never add a paid service or proprietary dependency.
- **Security:** `yaml.safe_load` only, no `eval`, no `shell=True`, confine paths, never log secrets.
- **UI design:** implement the original "Field Notebook" design language from `docs/13`; do not copy any other product's look.

## 4. Git & commit identity (strict)

- Every commit in this repository must be **authored and committed by the owner identity only**:
  `user.name = CodewithJha`, `user.email = <id>+CodewithJha@users.noreply.github.com` (set repo-local `git config`).
- **Never** add `Co-authored-by:` trailers, bot identities, or any other author/committer.
- Conventional Commits; branch `feat/T-NNN-short-name`; one task per PR; squash merge.
- Before pushing, verify: `git log --format='%an <%ae> | %cn <%ce>' origin/main..HEAD` shows only the owner identity.

## 5. Definition of Done

See `docs/32` §3 — all boxes must be ticked, including docs, config reference, traceability and CHANGELOG updates.

## 6. Useful commands (after M1)

`make setup` · `make lint` · `make typecheck` · `make test` · `make test-fast` · `make up` · `make demo` · `make docs-check` · `uv run roboprobe --help`

## 7. When you finish a task

Report: task id, requirements implemented, tests added, config keys added, docs changed, assumptions made, follow-ups.
