# RoboProbe developer entry points (docs/17 §3). Thin wrappers only: real configuration lives in
# backend/pyproject.toml and .pre-commit-config.yaml. Override any variable on the command line,
# e.g. `make test PYTEST_ARGS="-k selection"`.

UV          ?= uv
BACKEND_DIR ?= backend
UV_RUN      := $(UV) run --directory $(BACKEND_DIR)
PYTEST_ARGS ?=
FAST_MARKERS ?= unit or property or contract
XDIST_WORKERS ?= auto

.DEFAULT_GOAL := help
.PHONY: help setup lock lint format typecheck test test-fast test-cov pre-commit clean

help: ## List available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: ## Create the backend venv from uv.lock (all extras) and install git hooks
	$(UV) sync --locked --all-extras --directory $(BACKEND_DIR)
	$(UV_RUN) pre-commit install --install-hooks

lock: ## Regenerate backend/uv.lock after changing dependencies (never hand-edit it)
	$(UV) lock --directory $(BACKEND_DIR)

lint: ## Ruff lint + format check
	$(UV_RUN) ruff check .
	$(UV_RUN) ruff format --check .

format: ## Apply ruff fixes and formatting
	$(UV_RUN) ruff check --fix .
	$(UV_RUN) ruff format .

typecheck: ## mypy --strict on backend/src
	$(UV_RUN) mypy

test: ## Default pytest run (excludes `sim` and `slow`)
	$(UV_RUN) pytest $(PYTEST_ARGS)

test-fast: ## Unit, property and contract tests in parallel
	$(UV_RUN) pytest -m "$(FAST_MARKERS)" -n $(XDIST_WORKERS) $(PYTEST_ARGS)

test-cov: ## Default pytest run with the coverage gate from docs/18 §3
	$(UV_RUN) pytest --cov --cov-report=term-missing --cov-report=xml $(PYTEST_ARGS)

pre-commit: ## Run every pre-commit hook on the whole repository
	$(UV_RUN) pre-commit run --all-files

clean: ## Remove caches and build artefacts
	rm -rf $(BACKEND_DIR)/.pytest_cache $(BACKEND_DIR)/.mypy_cache $(BACKEND_DIR)/.ruff_cache \
		$(BACKEND_DIR)/htmlcov $(BACKEND_DIR)/coverage.xml $(BACKEND_DIR)/.coverage $(BACKEND_DIR)/dist
