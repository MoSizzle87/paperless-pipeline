# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# tini for clean PID 1, curl for debugging
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv from official image (pinned)
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app

# Step 1: install dependencies only (optimal Docker cache)
# Copying only spec files keeps this layer cached as long as deps don't change.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Step 2: copy source code and install the project itself
COPY src/ ./src/
COPY scripts/ ./scripts/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# venv created by uv lives in /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src

# Non-root user
RUN useradd --create-home --shell /bin/bash classifier \
    && chown -R classifier:classifier /app /opt/venv
USER classifier

RUN mkdir -p /app/logs

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "filethat.cli", "run"]
