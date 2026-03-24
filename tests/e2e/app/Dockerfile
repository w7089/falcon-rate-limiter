FROM python:3.14-slim

# Install uv
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv

WORKDIR /app

# uv sync installs into .venv by default; UV_PROJECT_ENVIRONMENT tells it
# to use the system Python's site-packages directly — no venv activation needed.
ENV UV_PROJECT_ENVIRONMENT=/usr/local

# Install dependencies from lockfile first — this layer is cached unless
# pyproject.toml or uv.lock change, even when library source changes.
COPY pyproject.toml uv.lock ./
RUN uv sync --no-dev --no-install-project

# Copy library source and install the project itself
COPY limiter/ ./limiter/
RUN uv sync --no-dev

# Copy the e2e app entrypoint
COPY tests/e2e/app/app.py ./app.py

EXPOSE 8080

CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "app:application"]
