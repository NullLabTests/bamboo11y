# syntax=docker/dockerfile:1.7
# Multi-stage build: compile the dashboard with Node, run the API on a slim Python image.
FROM node:22-alpine AS dashboard

WORKDIR /build/frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim AS runtime

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PYTHONPATH=/app/backend \
    BAMBOO11Y_ENVIRONMENT=container \
    BAMBOO11Y_DATABASE_URL=sqlite:////data/bamboo11y.db \
    BAMBOO11Y_SERVICE_CATALOG_PATH=/app/config/services.yaml \
    BAMBOO11Y_STATIC_DIR=/app/frontend/dist

WORKDIR /app

RUN groupadd --system bamboo11y \
    && useradd --system --gid bamboo11y --home-dir /app --shell /usr/sbin/nologin bamboo11y \
    && mkdir -p /data \
    && chown -R bamboo11y:bamboo11y /data

COPY backend/requirements.txt backend/requirements.txt
RUN pip install --no-cache-dir -r backend/requirements.txt

COPY backend/app backend/app
COPY config config
COPY scripts scripts
COPY --from=dashboard /build/frontend/dist frontend/dist

RUN chown -R bamboo11y:bamboo11y /app
USER bamboo11y

EXPOSE 8000
VOLUME ["/data"]

HEALTHCHECK --interval=15s --timeout=3s --start-period=10s --retries=3 \
  CMD python -c "import urllib.request; urllib.request.urlopen('http://127.0.0.1:8000/healthz', timeout=2)"

CMD ["uvicorn", "app.main:create_app", "--factory", "--host", "0.0.0.0", "--port", "8000"]
