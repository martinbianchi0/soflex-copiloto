# syntax=docker/dockerfile:1

# Etapa 1 · Node compila el panel a archivos estáticos.
FROM node:26-alpine AS panel
WORKDIR /panel
RUN npm install --global pnpm@12.15.0
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm build

# Etapa 2 · uv instala el backend y sus dependencias en un entorno virtual.
FROM python:3.13-slim AS backend
COPY --from=ghcr.io/astral-sh/uv:0.13.6 /uv /bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
# Primero sólo las dependencias: esta capa se reutiliza mientras no cambie `uv.lock`.
COPY backend/pyproject.toml backend/uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project
COPY backend/src ./src
RUN uv sync --frozen --no-dev --no-editable

# Etapa 3 · La imagen que corre: Python, el entorno y el panel. Sin Node ni uv.
FROM python:3.13-slim
RUN useradd --create-home --uid 10001 copiloto \
    && mkdir /data \
    && chown copiloto:copiloto /data
WORKDIR /app
COPY --from=backend /app/.venv /app/.venv
COPY --from=panel /panel/dist /app/static
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    STATIC_DIR=/app/static \
    SQLITE_PATH=/data/llamadas.sqlite
USER copiloto
EXPOSE 8000
VOLUME /data
HEALTHCHECK --interval=10s --timeout=3s --start-period=10s --retries=3 \
    CMD ["python", "-c", "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/api/health', timeout=2)"]
CMD ["uvicorn", "copiloto.main:app", "--host", "0.0.0.0", "--port", "8000"]
