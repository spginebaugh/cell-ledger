# syntax=docker/dockerfile:1.7
# One container: FastAPI serves /api and the built React app from the same origin.
# Build locally with `mise run docker:build`; Fly builds the same file on `mise run deploy`.

# ---------------------------------------------------------------- web build
FROM oven/bun:1.3 AS web
WORKDIR /src
COPY package.json bun.lock ./
COPY apps/web/package.json apps/web/
RUN bun install --frozen-lockfile
COPY biome.json ./
COPY apps/web apps/web
RUN bun run --cwd apps/web build

# ------------------------------------------------------------- python deps
FROM python:3.13-slim AS api
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /uvx /bin/
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app

# Dependencies first so they cache independently of our own source.
COPY pyproject.toml uv.lock ./
COPY apps/api/pyproject.toml apps/api/
COPY packages/core/pyproject.toml packages/core/
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-install-workspace

COPY apps/api apps/api
COPY packages/core packages/core
RUN --mount=type=cache,target=/root/.cache/uv \
    uv sync --frozen --no-dev --no-editable

COPY --from=web /src/apps/web/dist /app/web

# ------------------------------------------------------------------ runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    MPLBACKEND=Agg \
    CELL_LEDGER_DATA_DIR=/data \
    CELL_LEDGER_WEB_DIST=/app/web
RUN mkdir -p /data
VOLUME /data
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
    CMD python -c "import urllib.request,sys; sys.exit(urllib.request.urlopen('http://127.0.0.1:8000/api/health').status != 200)"

# One worker on purpose: SessionService keeps locks and a download semaphore in-process.
# State is in Supabase; /data is a cache. Scale the machine, not the process count.
CMD ["uvicorn", "--factory", "cell_ledger_api.main:create_app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1", "--proxy-headers", "--forwarded-allow-ips", "*"]
