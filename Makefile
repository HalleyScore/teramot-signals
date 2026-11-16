.PHONY: install fmt lint typecheck test check

install:        ## Sync the virtualenv from pyproject + uv.lock
	uv sync

fmt:            ## Auto-format
	uv run ruff format src tests

lint:           ## Lint (ruff)
	uv run ruff check src tests

typecheck:      ## Static type check (basedpyright)
	uv run basedpyright

test:           ## Run the test suite
	uv run pytest

check: lint typecheck test  ## Run all CI checks locally
