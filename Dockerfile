# birbTrack: the public bird site, its Discord posts and the weekly report. Data lives in /data.
FROM node:22-alpine AS web
WORKDIR /web
COPY frontend/package.json frontend/package-lock.json ./
RUN npm ci --no-audit --no-fund
COPY frontend/ ./
RUN npm run build

FROM python:3.12-slim
ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 BT_DATA=/data BT_STATIC=/app/frontend/dist BT_PORT=8894
RUN apt-get update && apt-get install -y --no-install-recommends tzdata && rm -rf /var/lib/apt/lists/*
WORKDIR /app/backend
COPY backend/requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt
COPY backend/ ./
COPY --from=web /web/dist /app/frontend/dist
RUN useradd --uid 1000 --gid 100 --no-create-home birbtrack && mkdir -p /data && chown 1000:100 /data
USER 1000:100
VOLUME /data
EXPOSE 8894
HEALTHCHECK --interval=60s --timeout=5s CMD ["python3", "healthcheck.py"]
CMD ["python3", "serve.py"]
