# syntax=docker/dockerfile:1
# Stage 1: build the Vue/Three.js frontend.
FROM node:22-alpine AS web
WORKDIR /web
COPY apps/web/package.json apps/web/package-lock.json* ./
RUN npm ci --no-audit --no-fund || npm install --no-audit --no-fund
COPY apps/web/ ./
RUN npm run build

# Stage 2: API + static files on one origin.
FROM python:3.11-slim
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 EARTHSIM_STORAGE_ROOT=/data
ARG EARTHSIM_EXTRAS=""
WORKDIR /app
COPY pyproject.toml ./
COPY backend/ ./backend/
COPY config/ ./config/
RUN pip install --upgrade pip && \
    pip install ./backend && \
    (test -z "$EARTHSIM_EXTRAS" || pip install "earthsim[$EARTHSIM_EXTRAS]")
COPY --from=web /web/dist/ /app/apps/web/dist/
RUN mkdir -p /data && useradd -m -u 10001 earthsim && chown -R earthsim:earthsim /app /data
USER earthsim
EXPOSE 8080
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import urllib.request;urllib.request.urlopen('http://127.0.0.1:8080/api/v1/health',timeout=3)" || exit 1
CMD ["python", "-m", "uvicorn", "earthsim.api.app:app", "--host", "0.0.0.0", "--port", "8080"]
