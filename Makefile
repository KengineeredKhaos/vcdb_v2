# -------- Config --------
.RECIPEPREFIX := >
PY := PYTHONPATH=.
FLASK := FLASK_APP=app
VENV_BIN := ./bin
PYTHON := $(VENV_BIN)/python
FLASK_CLI := $(VENV_BIN)/flask
PKG=app
SCRIPTS=scripts/Python
FMT_TARGETS=$(PKG) $(SCRIPTS)

DB := var/app-instance/dev.db

# Default target
.DEFAULT_GOAL := help

# -------- Tasks --------
.PHONY: help
help: ## Show this help
> @grep -E '^[a-zA-Z0-9_.-]+:.*?## .+' $(MAKEFILE_LIST) | \
>  sed -e 's/:.*##/: /' | sort

.PHONY: run
run: ## Run dev server (flask run)
> @$(FLASK) $(FLASK_CLI) run

.PHONY: routes
routes: ## Print route table
> @$(PY) $(PYTHON) scripts/Python/print_routes.py

.PHONY: db.up
db.up: ## Apply Alembic migrations (upgrade to head)
> @$(FLASK) $(FLASK_CLI) db upgrade

.PHONY: db.revision
db.revision: ## Create autogen migration (NAME="message")
> @test -n "$(NAME)" || (echo "Usage: make db.revision NAME='your message'" && exit 1)
> @$(FLASK) $(FLASK_CLI) db revision --autogenerate -m "$(NAME)"

.PHONY: db.reset
db.reset: ## Blow away dev DB, recreate, migrate, seed
> @echo "Removing $(DB) ..."
> @rm -f $(DB)
> @$(FLASK) $(FLASK_CLI) db upgrade
> @$(PY) $(PYTHON) scripts/Python/seed_minimal.py

.PHONY: seed
seed: ## Seed minimal entities/users
> @$(PY) $(PYTHON) scripts/Python/seed_minimal.py

.PHONY: fmt lint type fix changed prepush


type:
> pyright

fix:
> ruff check . --fix
> black $(FMT_TARGETS)

# Only lint/format files changed vs main (rename 'origin/main' if needed)
changed:
> @git diff --name-only --diff-filter=ACMR origin/main... | \
> grep -E '\.py$$' | \
> xargs -r ruff check --fix
> @git diff --name-only --diff-filter=ACMR origin/main... | \
> grep -E '^(app|scripts/Python)/.*\.py$$' | \
> xargs -r black

# Run everything quick before pushing
# prepush: fix type lint

.PHONY: smoke
smoke: ## Hit healthz and hello endpoints
> @bash scripts/Shell/smoke_slices.sh

.PHONY: verify
verify: ## Verify ledger chain
> @$(PY) $(PYTHON) scripts/Python/verify_ledger_chain.py

.PHONY: sanity
sanity: ## Boot sanity + entity_read probe
> @$(PY) $(PYTHON) scripts/Python/sanity_check.py

.PHONY: test
test: ## Run unit tests (pytest)
> @$(PY) $(PYTHON) -m pytest -q

.PHONY: lint
lint: ## Lint (ruff) and type-check (pyright) if available
> @command -v ruff >/dev/null 2>&1 && ruff check . || echo "ruff not installed"
> @command -v pyright >/dev/null 2>&1 && pyright || echo "pyright not installed"

.PHONY: fmt
fmt: ## Auto-format (ruff + black) if available
> @command -v ruff >/dev/null 2>&1 && ruff check --fix . || echo "ruff not installed"
> @command -v black >/dev/null 2>&1 && black . || echo "black not installed"
