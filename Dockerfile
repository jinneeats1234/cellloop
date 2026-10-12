# Single-service image of CellLoop: the React web app and the FastAPI API in one container.
# Used by render.yaml (Render free web service); works on any Docker host.
#   docker build -t cellloop . && docker run -p 10000:10000 cellloop   →  http://localhost:10000
#
# The API serves the built React app (STATIC_DIR) and /api from one URL, so no proxy or CORS.
# Demo mode: SQLite + local files inside the container, re-seeded with demo data on each start.

# ---- 1. Build the React app -------------------------------------------------------------
FROM node:22-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
# --include=dev: the build tools are devDependencies, and hosts may set NODE_ENV=production.
RUN npm ci --include=dev --no-audit --no-fund
COPY frontend/ ./
RUN npm run build \
 && find dist -type f \( -name '*.js' -o -name '*.css' -o -name '*.svg' -o -name '*.html' \) -exec gzip -9 -k {} \;

# ---- 2. Python runtime with the API + built web app --------------------------------------
FROM python:3.14-slim AS app
ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    PIP_DISABLE_PIP_VERSION_CHECK=1
WORKDIR /app/backend

COPY backend/requirements.txt ./
RUN pip install -r requirements.txt

COPY backend/app ./app
COPY samples /app/samples
COPY --from=web /web/dist /app/frontend/dist

# Run as an unprivileged user; data/ holds the demo SQLite database and uploads.
RUN useradd --create-home --uid 10001 cellloop \
 && mkdir -p /app/backend/data \
 && chown -R cellloop /app/backend
USER cellloop

ENV APP_ENV=dev \
    STATIC_DIR=/app/frontend/dist \
    CELLLOOP_SAMPLES_DIR=/app/samples \
    DATABASE_URL=sqlite:///./data/cellloop.db \
    LOCAL_STORAGE_DIR=./data/uploads \
    PORT=10000
EXPOSE 10000

# Seed demo data (only when the database is empty), then serve. --proxy-headers makes client
# IPs (used by rate limiting) come from the host's load balancer, not the proxy itself.
CMD ["sh", "-c", "python -m app.scripts.seed && exec python -m uvicorn app.main:app --host 0.0.0.0 --port ${PORT:-10000} --proxy-headers --forwarded-allow-ips '*'"]
