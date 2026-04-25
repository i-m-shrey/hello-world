# syntax=docker/dockerfile:1
FROM python:3.11-slim-bookworm

ENV PYTHONDONTWRITEBYTECODE=1 \
    PYTHONUNBUFFERED=1 \
    PIP_NO_CACHE_DIR=1

# System libs + Chrome/Driver
RUN apt-get update && DEBIAN_FRONTEND=noninteractive apt-get install -y --no-install-recommends \
      ca-certificates curl unzip \
      chromium chromium-driver \
      libnss3 libgdk-pixbuf-2.0-0 libgtk-3-0 libx11-6 libx11-xcb1 libxcb1 libxcomposite1 libxdamage1 libxrandr2 \
      libasound2 libgbm1 libxshmfence1 libxi6 libxext6 \
      fonts-liberation fonts-noto-color-emoji && \
    rm -rf /var/lib/apt/lists/*

# Point Selenium to system Chrome/Driver
ENV CHROME_BIN=/usr/bin/chromium \
    CHROMEDRIVER_PATH=/usr/bin/chromedriver

WORKDIR /app

# Install Python deps
COPY requirements.txt /app/requirements.txt
RUN pip install --no-cache-dir --upgrade pip && \
    pip install --no-cache-dir -r /app/requirements.txt

# Copy project
COPY . /app

# Gunicorn
ENV GUNICORN_CMD_ARGS="--timeout 900 --graceful-timeout 120"
EXPOSE 8080

# Run runner Flask app
CMD ["gunicorn", "--bind", "0.0.0.0:8080", "--workers", "1", "--threads", "4", \
     "--timeout", "900", "--graceful-timeout", "120", "runner:app"]
