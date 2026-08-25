# ── base: dependencias de ejecución ──────────────────────────
FROM python:3.12-slim AS base
ENV PYTHONUNBUFFERED=1 \
    PYTHONDONTWRITEBYTECODE=1
COPY --from=ghcr.io/astral-sh/uv:latest /uv /usr/local/bin/uv
WORKDIR /app
COPY requirements.txt ./
RUN uv pip install --system --no-cache -r requirements.txt

# ── dev: + herramientas de prueba, código por volumen ────────
FROM base AS dev
COPY requirements-dev.txt ./
RUN uv pip install --system --no-cache -r requirements-dev.txt
COPY . .
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${API_PORT:-8000} --reload"]

# ── prod: imagen delgada, usuario sin privilegios ────────────
FROM base AS prod
COPY . .
RUN useradd --create-home --uid 10001 zonepark && chown -R zonepark:zonepark /app
USER zonepark
CMD ["sh", "-c", "uvicorn app.main:app --host 0.0.0.0 --port ${API_PORT:-8000}"]
