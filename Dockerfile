# Parity API for Render (free tier, Docker).
# The Playwright base image ships Chromium and every system library it needs;
# its version MUST match the playwright pin in pyproject.toml (1.56.0).
FROM mcr.microsoft.com/playwright/python:v1.56.0-noble

ENV PYTHONUNBUFFERED=1 \
    UV_LINK_MODE=copy \
    UV_COMPILE_BYTECODE=1 \
    PARITY_DATA_DIR=/tmp/parity-scans

COPY --from=ghcr.io/astral-sh/uv:0.8 /uv /usr/local/bin/uv

WORKDIR /app
# Dependencies first (cached layer), then the code.
COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-dev --no-install-project
COPY src ./src
RUN uv sync --frozen --no-dev

# Render sets $PORT. One worker: scans run one at a time through an in-memory queue.
CMD ["sh", "-c", "uv run --no-sync uvicorn parity.api.app:app --host 0.0.0.0 --port ${PORT:-8000} --workers 1"]
