# RoboProbe developer entry points (docs/17 §3). Thin wrappers only: real configuration lives in
# backend/pyproject.toml and .pre-commit-config.yaml. Override any variable on the command line,
# e.g. `make test PYTEST_ARGS="-k selection"`.

UV          ?= uv
BACKEND_DIR ?= backend
UV_RUN      := $(UV) run --directory $(BACKEND_DIR)
PYTEST_ARGS ?=
FAST_MARKERS ?= unit or property or contract
XDIST_WORKERS ?= auto
# Paths below are relative to BACKEND_DIR because Python tools run there.
SCRIPTS_DIR ?= ../scripts
CONFIG_DOCS_SCRIPT ?= $(SCRIPTS_DIR)/gen_config_docs.py
PNPM        ?= pnpm
WEB_DIR     ?= web
# cd (not --dir) so corepack resolves the pnpm version pinned in web/package.json.
PNPM_WEB    := cd $(WEB_DIR) && $(PNPM)
DOCS_CHECKS ?=
PYTHON      ?= python3
# Docker Compose stack (docs/17 §4). `make up PROFILES="core dev"` also publishes Postgres on loopback.
DOCKER      ?= docker
PROFILES    ?= core
SECRETS_DIR ?= secrets
DB_PASSWORD_FILE := $(SECRETS_DIR)/db_password
COMPOSE_FILE ?= docker/compose.yaml
# Created up front so Docker does not create the bind-mount source as root (compose.yaml mounts it).
ARTIFACTS_DIR ?= data/artifacts
COMPOSE     := $(DOCKER) compose -f $(COMPOSE_FILE) $(if $(wildcard .env),--env-file .env)
COMPOSE_UP  := $(COMPOSE) $(addprefix --profile ,$(PROFILES))
# `make up UP_FLAGS=` runs pulled release images instead of building the backend locally.
UP_FLAGS    ?= --build

.DEFAULT_GOAL := help
.PHONY: help setup lock lint format typecheck test test-fast test-cov pre-commit docs-check clean \
	config-docs config-docs-check openapi up down db-up logs ps backup restore observability

BACKUP_DIR ?= backups
BACKUP_RETENTION ?= 7

help: ## List available targets
	@grep -hE '^[a-zA-Z_-]+:.*?## ' $(MAKEFILE_LIST) | \
		awk 'BEGIN {FS = ":.*?## "}; {printf "  \033[36m%-12s\033[0m %s\n", $$1, $$2}'

setup: $(DB_PASSWORD_FILE) ## Install backend + web deps and git hooks; create the local DB secret
	$(UV) sync --locked --all-extras --directory $(BACKEND_DIR)
	$(PNPM_WEB) install --frozen-lockfile
	$(UV_RUN) pre-commit install --install-hooks

lock: ## Regenerate backend/uv.lock after changing dependencies (never hand-edit it)
	$(UV) lock --directory $(BACKEND_DIR)

lint: ## Ruff + import-linter contracts (backend); ESLint (0 warnings) + Prettier + Stylelint + token freshness (web)
	$(UV_RUN) ruff check . $(SCRIPTS_DIR)
	$(UV_RUN) ruff format --check . $(SCRIPTS_DIR)
	$(UV_RUN) lint-imports
	$(PNPM_WEB) lint

format: ## Apply ruff fixes and formatting; Prettier for web
	$(UV_RUN) ruff check --fix . $(SCRIPTS_DIR)
	$(UV_RUN) ruff format . $(SCRIPTS_DIR)
	$(PNPM_WEB) format

typecheck: ## mypy --strict on backend/src and scripts/; tsc --build (strict) for web
	$(UV_RUN) mypy
	$(UV_RUN) mypy $(SCRIPTS_DIR)
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

config-docs: ## Regenerate docs/27 §4 tables, .env.example and roboprobe.example.toml from settings
	$(UV_RUN) python $(CONFIG_DOCS_SCRIPT)

config-docs-check: ## Fail (with a diff) if generated configuration docs/templates are stale
	$(UV_RUN) python $(CONFIG_DOCS_SCRIPT) --check

openapi: ## Regenerate api/openapi.json from the FastAPI app (T-084b)
	$(UV_RUN) python $(SCRIPTS_DIR)/export_openapi.py

$(DB_PASSWORD_FILE): ## Generate a random local DB password (git-ignored; never overwritten)
	@mkdir -p $(SECRETS_DIR) && chmod 700 $(SECRETS_DIR)
	@umask 022 && $(PYTHON) -c 'import secrets; print(secrets.token_urlsafe(32))' > $@
	@echo "created $@"

up: $(DB_PASSWORD_FILE) ## Start the stack (PROFILES, default core); fails if the migrate job fails
	@mkdir -p $(ARTIFACTS_DIR)
	$(COMPOSE_UP) up -d $(UP_FLAGS)
	$(COMPOSE_UP) wait migrate

down: ## Stop and remove every container and the network (volumes kept)
	$(COMPOSE) --profile '*' down --remove-orphans

db-up: $(DB_PASSWORD_FILE) ## Start only Postgres and wait until healthy (PROFILES="core dev" to publish it)
	$(COMPOSE_UP) up -d --wait postgres $(if $(filter dev,$(PROFILES)),postgres-port)

logs: ## Follow logs of all running services
	$(COMPOSE) --profile '*' logs -f

ps: ## List stack containers
	$(COMPOSE) --profile '*' ps -a

backup: ## pg_dump custom format plus artefact archive (doc 29 §7)
	BACKUP_DIR="$(BACKUP_DIR)" BACKUP_RETENTION="$(BACKUP_RETENTION)" \
		scripts/backup.sh --out "$(BACKUP_DIR)"

restore: ## Restore BACKUP=path (set FORCE=1 to overwrite a non-empty database)
	scripts/restore.sh $(if $(FORCE),--force,) "$(BACKUP)"

observability: $(DB_PASSWORD_FILE) ## Prometheus, Grafana and Jaeger (profile observability)
	@mkdir -p $(ARTIFACTS_DIR)
	$(COMPOSE) --profile observability up -d --wait prometheus grafana otel-collector jaeger
