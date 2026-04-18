.PHONY: lint format type-check test all install check e2e-up e2e-down test-e2e e2e version release release-patch release-minor release-major release-tag

E2E_COMPOSE := docker-compose -f tests/e2e/docker-compose.yml

install:
	uv sync

lint:
	uv run ruff check .

lint-auto-fix:
    uv run ruff check --fix .:

format:
	uv run ruff format .

type-check:
	uv run mypy limiter

test:
	uv run pytest

check: lint type-check test

all: format check

version:
	@uv run python scripts/release.py current-version

release: release-patch

release-patch:
	@uv run python scripts/release.py bump patch

release-minor:
	@uv run python scripts/release.py bump minor

release-major:
	@uv run python scripts/release.py bump major

release-tag:
	@uv run python scripts/release.py release-tag

e2e-up:
	$(E2E_COMPOSE) up --build -d
	@echo "Waiting for app to be healthy..."
	@for i in $$(seq 1 30); do \
		id=$$($(E2E_COMPOSE) ps -q app 2>/dev/null); \
		status=$$(docker inspect --format='{{.State.Health.Status}}' $$id 2>/dev/null); \
		if [ "$$status" = "healthy" ]; then echo "App is healthy."; exit 0; fi; \
		sleep 2; \
	done; \
	echo "ERROR: App did not become healthy in time." && exit 1

e2e-down:
	$(E2E_COMPOSE) down --volumes

test-e2e:
	uv run pytest tests/e2e/ -v

e2e:
	$(MAKE) e2e-up
	uv run pytest tests/e2e/ -v; ret=$$?; $(MAKE) e2e-down; exit $$ret
