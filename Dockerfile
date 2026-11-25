# syntax=docker/dockerfile:1
#
# ChatIApp en una sola imagen (docs/adr/0008-imagen-unica-con-sqlite.md):
# FastAPI sirve la interfaz en / y la API en /api/v1; la base de la app es
# SQLite en el volumen /data.
#
#   docker build -t chatiapp .
#   docker run -p 8080:8080 -v chatiapp:/data chatiapp

# --- Etapa 1: interfaz web (React + Vite) ---
FROM node:22-slim AS web
ENV COREPACK_ENABLE_DOWNLOAD_PROMPT=0
RUN corepack enable
WORKDIR /web
COPY frontend/package.json frontend/pnpm-lock.yaml ./
RUN pnpm install --frozen-lockfile
COPY frontend/ ./
RUN pnpm run build

# --- Etapa 2: backend y dependencias en un entorno virtual ---
FROM python:3.12-slim AS backend
COPY --from=ghcr.io/astral-sh/uv:0.9 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY backend/pyproject.toml backend/uv.lock ./
# Solo las dependencias (capa cacheable). El driver de PostgreSQL va incluido
# para poder cambiar de base sin reconstruir la imagen.
RUN uv sync --locked --no-dev --no-install-project --extra postgres
COPY backend/app ./app
COPY backend/alembic ./alembic
COPY backend/alembic.ini ./
RUN uv sync --locked --no-dev --extra postgres

# --- Etapa 3: imagen final, sin uv, Node ni herramientas de compilación ---
FROM python:3.12-slim
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1 \
    CHATIAPP_ENV=production \
    CHATIAPP_DATA_DIR=/data \
    CHATIAPP_DATABASE_URL=sqlite:////data/chatiapp.db \
    CHATIAPP_STATIC_DIR=/app/static
RUN groupadd --system --gid 10001 chatiapp \
    && useradd --system --uid 10001 --gid chatiapp --home-dir /app --shell /usr/sbin/nologin chatiapp \
    && mkdir /data \
    && chown chatiapp:chatiapp /data
WORKDIR /app
COPY --from=backend --chown=chatiapp:chatiapp /app /app
COPY --from=web --chown=chatiapp:chatiapp /web/dist /app/static
COPY --chown=chatiapp:chatiapp examples /app/examples
COPY --chmod=0755 backend/docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
USER chatiapp
VOLUME ["/data"]
EXPOSE 8080
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8080/api/v1/health', timeout=2)"]
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8080"]
