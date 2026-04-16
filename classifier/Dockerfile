# syntax=docker/dockerfile:1.7
FROM python:3.12-slim AS base

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    UV_PYTHON_DOWNLOADS=never \
    UV_PROJECT_ENVIRONMENT=/opt/venv

# tini pour PID 1 propre, curl pour debug
RUN apt-get update && apt-get install -y --no-install-recommends \
        tini \
        curl \
    && rm -rf /var/lib/apt/lists/*

# Install uv depuis l'image officielle (pinnée)
COPY --from=ghcr.io/astral-sh/uv:0.5.11 /uv /uvx /usr/local/bin/

WORKDIR /app

# Étape 1 : install des dépendances uniquement (cache Docker optimal)
# On copie uniquement les fichiers de spec pour que ce layer soit caché
# tant que les deps ne changent pas.
COPY pyproject.toml uv.lock ./
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-install-project --no-dev

# Étape 2 : copie du code et install du projet lui-même
COPY src/ ./src/
COPY scripts/ ./scripts/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev

# Le venv créé par uv est dans /opt/venv
ENV PATH="/opt/venv/bin:$PATH" \
    PYTHONPATH=/app/src

# Utilisateur non-root
RUN useradd --create-home --shell /bin/bash classifier \
    && chown -R classifier:classifier /app /opt/venv
USER classifier

RUN mkdir -p /app/logs

ENTRYPOINT ["/usr/bin/tini", "--"]
CMD ["python", "-m", "pipeline.cli", "run"]
