FROM python:3.14-slim AS builder

COPY --from=ghcr.io/astral-sh/uv:latest /uv /uvx /bin/

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    UV_COMPILE_BYTECODE=1 \
    UV_LINK_MODE=copy

WORKDIR /app

COPY pyproject.toml uv.lock README.md mkdocs.yml ./
COPY docs ./docs
COPY app ./app

RUN uv sync --frozen --no-default-groups --group docs \
    && uv run mkdocs build --strict


FROM nginx:1.29-alpine

COPY docker/docs/nginx.conf /etc/nginx/conf.d/default.conf
COPY --from=builder /app/site /usr/share/nginx/html

EXPOSE 80

HEALTHCHECK --interval=15s --timeout=5s --start-period=5s --retries=3 \
    CMD wget -qO- http://127.0.0.1/ >/dev/null || exit 1
