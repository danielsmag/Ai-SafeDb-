FROM node:24-slim AS frontend-builder

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend ./
RUN npm run build


FROM python:3.14-slim

# Node.js is needed by stdio server definitions that launch `npx ...`.
RUN apt-get update \
    && apt-get install -y --no-install-recommends nodejs npm \
    && rm -rf /var/lib/apt/lists/*

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy \
    UV_NO_DEV=1

WORKDIR /app

COPY pyproject.toml uv.lock README.md ./
RUN uv sync --frozen --no-install-project

COPY app ./app
COPY policies ./policies
COPY workflows ./workflows
COPY sources ./sources
COPY outputs ./outputs
COPY --from=frontend-builder /frontend/dist ./frontend/dist
RUN uv sync --frozen --no-dev

ENV PATH="/app/.venv/bin:$PATH"

RUN useradd --create-home --uid 10001 gateway
USER gateway

EXPOSE 8000

HEALTHCHECK --interval=15s --timeout=5s --start-period=10s --retries=3 \
    CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/health').read()"

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
