FROM python:3.12-slim AS builder

RUN pip install --no-cache-dir uv

WORKDIR /app

COPY pyproject.toml ./

RUN uv venv /app/.venv && \
    uv pip compile pyproject.toml -o /tmp/requirements.txt && \
    uv pip install --python /app/.venv/bin/python -r /tmp/requirements.txt

FROM builder AS test-builder

RUN uv pip compile pyproject.toml --extra dev -o /tmp/requirements-dev.txt && \
    uv pip install --python /app/.venv/bin/python -r /tmp/requirements-dev.txt

COPY filethat/ ./filethat/
COPY tests/ ./tests/

ENV PYTHONPATH=/app


FROM python:3.12-slim

RUN apt-get update && apt-get install -y --no-install-recommends \
    tesseract-ocr \
    tesseract-ocr-fra \
    tesseract-ocr-eng \
    ghostscript \
    qpdf \
    poppler-utils \
    unpaper \
    pngquant \
    && rm -rf /var/lib/apt/lists/*

COPY --from=builder /app/.venv /app/.venv

ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1

WORKDIR /app

COPY filethat/ ./filethat/
COPY config.yaml ./

ENTRYPOINT ["python", "-m", "filethat"]
CMD ["scan"]
