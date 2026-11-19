# RoboProbe developer entry points (docs/17 §3). Thin wrappers only: real configuration lives in
# backend/pyproject.toml and .pre-commit-config.yaml. Override any variable on the command line,
# e.g. `make test PYTEST_ARGS="-k selection"`.

UV          ?= uv
BACKEND_DIR ?= backend
UV_RUN      := $(UV) run --directory $(BACKEND_DIR)
PYTEST_ARGS ?=
FAST_MARKERS ?= unit or property or contract
XDIST_WORKERS ?= auto
PNPM        ?= pnpm
WEB_DIR     ?= web
# cd (not --dir) so corepack resolves the pnpm version pinned in web/package.json.
PNPM_WEB    := cd $(WEB_DIR) && $(PNPM)
DOCS_CHECKS ?=

.DEFAULT_GOAL := help
.PHONY: help setup lock lint format typecheck test test-fast test-cov pre-commit docs-check clean

help: ## List available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Install backend (uv.lock, all extras) and web (pnpm-lock.yaml) deps, then git hooks
	$(UV) sync --locked --all-extras --directory $(BACKEND_DIR)
	$(PNPM_WEB) install --frozen-lockfile
	$(UV_RUN) pre-commit install --install-hooks

lock: ## Regenerate backend/uv.lock after changing dependencies (never hand-edit it)
	$(UV) lock --directory $(BACKEND_DIR)

lint: ## Ruff + import-linter contracts (backend); ESLint (0 warnings) + Prettier check (web)
	$(UV_RUN) ruff check .
	$(UV_RUN) ruff format --check .
	$(UV_RUN) lint-imports
	$(PNPM_WEB) lint

format: ## Apply ruff fixes and formatting; Prettier for web
	$(UV_RUN) ruff check --fix .
	$(UV_RUN) ruff format .
	$(PNPM_WEB) format

typecheck: ## mypy --strict on backend/src; tsc --build (strict) for web
	$(UV_RUN) mypy
	$(PNPM_WEB) typecheck

test: ## Default pytest run (excludes `sim` and `slow`) and Vitest for web
	$(UV_RUN) pytest $(PYTEST_ARGS)
	$(PNPM_WEB) test

test-fast: ## Unit, property and contract tests in parallel
	$(UV_RUN) pytest -m "$(FAST_MARKERS)" -n $(XDIST_WORKERS) $(PYTEST_ARGS)

test-cov: ## Default pytest run with the coverage gate from docs/18 §3 (backend and web)
	$(UV_RUN) pytest --cov --cov-report=term-missing --cov-report=xml $(PYTEST_ARGS)
	$(PNPM_WEB) test:coverage

pre-commit: ## Run every pre-commit hook on the whole repository
	$(UV_RUN) pre-commit run --all-files

docs-check: ## Docs gate: markdownlint, Mermaid render, links, ADR index (DOCS_CHECKS="links" to subset)
	scripts/check_docs.sh $(DOCS_CHECKS)

clean: ## Remove caches and build artefacts
	rm -rf $(BACKEND_DIR)/.pytest_cache $(BACKEND_DIR)/.mypy_cache $(BACKEND_DIR)/.ruff_cache \
		$(BACKEND_DIR)/htmlcov $(BACKEND_DIR)/coverage.xml $(BACKEND_DIR)/.coverage $(BACKEND_DIR)/dist \
		$(WEB_DIR)/dist $(WEB_DIR)/coverage
