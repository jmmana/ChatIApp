# syntax=docker/dockerfile:1

# --- Etapa 1: dependencias y paquete en un entorno virtual ---
FROM python:3.12-slim AS builder
COPY --from=ghcr.io/astral-sh/uv:0.5 /uv /usr/local/bin/uv
ENV UV_COMPILE_BYTECODE=1 UV_LINK_MODE=copy UV_PYTHON_DOWNLOADS=never
WORKDIR /app
COPY pyproject.toml uv.lock ./
# Solo las dependencias (capa cacheable); el driver de PostgreSQL va incluido.
RUN uv sync --locked --no-dev --no-install-project --extra postgres
COPY app ./app
COPY alembic ./alembic
COPY alembic.ini ./
RUN uv sync --locked --no-dev --extra postgres

# --- Etapa 2: imagen final, sin uv ni herramientas de compilación ---
FROM python:3.12-slim AS runtime
ENV PATH="/app/.venv/bin:$PATH" \
    PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
RUN groupadd --system --gid 10001 chatiapp \
    && useradd --system --uid 10001 --gid chatiapp --home-dir /app --shell /usr/sbin/nologin chatiapp
WORKDIR /app
COPY --from=builder --chown=chatiapp:chatiapp /app /app
COPY --chmod=0755 docker-entrypoint.sh /usr/local/bin/docker-entrypoint.sh
USER chatiapp
EXPOSE 8000
HEALTHCHECK --interval=10s --timeout=3s --start-period=30s --retries=5 \
    CMD ["python", "-c", "import urllib.request as u; u.urlopen('http://127.0.0.1:8000/api/v1/health', timeout=2)"]
ENTRYPOINT ["docker-entrypoint.sh"]
CMD ["uvicorn", "app.main:app", "--host", "0.0.0.0", "--port", "8000"]
