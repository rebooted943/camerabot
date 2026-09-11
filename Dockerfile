# Always-on ArbitrageSniper dashboard + scanner (Option A hosted deployment).
# Uses the official Playwright image so Chromium + system deps are preinstalled
# and match the pinned playwright version.
FROM mcr.microsoft.com/playwright/python:v1.44.0-jammy

WORKDIR /app

# Install Python deps first for better layer caching.
COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

# App code (thresholds.json is copied so a fresh volume can be seeded from it).
COPY . .

ENV DATA_DIR=/data \
    HEADLESS=true \
    PORT=8000 \
    PYTHONUNBUFFERED=1

# Persistent state (SQLite + thresholds.json) lives on a mounted volume.
RUN mkdir -p /data
VOLUME ["/data"]

EXPOSE 8000

# Serve the API + SPA. The scanner runs in-process ("Scan now" + optional
# SCAN_INTERVAL_MIN scheduler), so this single service is fully self-contained.
CMD ["sh", "-c", "uvicorn arbitrage_sniper.web.app:app --host 0.0.0.0 --port ${PORT:-8000}"]
