# Nexonic TV Server: one image with the web app and the server.
FROM node:22-bookworm-slim AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npx -y npm@11.6.2 ci --no-audit --no-fund
COPY frontend ./
RUN npm run build

FROM python:3.12-slim-bookworm
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1 \
    NEXONIC_HOST=0.0.0.0 NEXONIC_PORT=8000 NEXONIC_DATA_DIR=/app/local-data PYTHONPATH=/app
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg \
    && rm -rf /var/lib/apt/lists/* && useradd --create-home --uid 10001 nexonic
WORKDIR /app
COPY backend/requirements.txt backend/requirements.txt
RUN pip install -r backend/requirements.txt
COPY backend backend
COPY --from=web /web/dist frontend/dist
RUN mkdir -p /app/local-data && chown -R nexonic:nexonic /app/local-data
USER nexonic
VOLUME ["/app/local-data"]
EXPOSE 8000
HEALTHCHECK --interval=30s --timeout=5s --start-period=20s \
  CMD python -c "import os,urllib.request;urllib.request.urlopen(f'http://127.0.0.1:{os.environ.get(\"NEXONIC_PORT\",\"8000\")}/api/health')"
CMD ["sh", "-c", "exec python -m uvicorn backend.app.main:app --host \"$NEXONIC_HOST\" --port \"$NEXONIC_PORT\""]
