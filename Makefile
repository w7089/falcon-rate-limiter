.PHONY: lint format type-check test all install check

install:
	uv sync

lint:
	uv run ruff check .

lint-auto-fix:
    uv run ruff check --fix .:

format:
	uv run ruff format .

type-check:
	uv run mypy .

test:
	uv run pytest

check: lint type-check test

all: format check

