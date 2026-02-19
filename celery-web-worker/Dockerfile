# Dockerfile for Celery Website Crawling Worker
# Optimized for minimal image size by copying only required directories
# Build image: docker build -t knowledgebot-celery-web-worker .
# Run: docker run -e REDIS_URL=redis://redis:6379/1 knowledgebot-celery-web-worker

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies only (no build tools after pip install)
# Note: Removed chromium and chromium-driver - Playwright manages browser installation
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy and install requirements files first (for better caching)
COPY celery-web-worker/requirements.txt /tmp/web-requirements.txt
COPY shared/requirements-otel.txt /tmp/otel-requirements.txt

# Install Python dependencies with better caching
RUN pip install --no-cache-dir --no-warn-script-location \
    -r /tmp/web-requirements.txt \
    -r /tmp/otel-requirements.txt

# Install Playwright browsers (required by Crawl4AI for web scraping)
RUN python -m playwright install chromium && \
    python -m playwright install-deps chromium

# Copy only required directories (not entire repository)
COPY celery-web-worker /app/celery-web-worker
COPY shared /app/shared

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH="/app"

# Change to service directory and start Celery worker for web_crawling queue
WORKDIR /app/celery-web-worker
CMD ["celery", "-A", "celery_app", "worker", "-Q", "web_crawling", "-l", "info", "-c", "1", "--max-tasks-per-child=100"]
