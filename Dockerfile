FROM node:22-slim AS frontend-build

WORKDIR /frontend
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim

ENV PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1 \
    UV_LINK_MODE=copy \
    PYTHONPATH=/app

WORKDIR /app

# uv (deterministic Python dep manager)
RUN pip install --no-cache-dir uv==0.5.*

# Deps layer (cached when pyproject.toml / uv.lock are unchanged).
# --no-install-project means uv doesn't try to read README.md (referenced by pyproject's
# `readme` field) for project metadata, which would fail in this layer since README isn't
# copied yet. PYTHONPATH=/app makes `from app.foo import ...` resolve against /app/app/.
COPY pyproject.toml uv.lock ./
RUN uv sync --frozen --no-dev --no-install-project

# App code layer (cache busts here when code changes; fast rebuild)
COPY app/ ./app/
COPY data/ ./data/
COPY docs/ ./docs/
COPY --from=frontend-build /frontend/dist ./frontend/dist

EXPOSE 8080

CMD ["sh", "-c", ".venv/bin/uvicorn app.api.main:api --host 0.0.0.0 --port ${PORT:-8080}"]
