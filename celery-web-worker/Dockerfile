# Dockerfile for Celery Website Crawling Worker
# Optimized for minimal image size by copying only required directories
# Build image: docker build -t knowledgebot-celery-web-worker .
# Run: docker run -e REDIS_URL=redis://redis:6379/1 knowledgebot-celery-web-worker

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies for Playwright/Chromium
# These are the minimal dependencies needed for browser automation
RUN apt-get update && \
    apt-get upgrade -y && \
    apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    postgresql-client \
    ca-certificates \
    libasound2 \
    libatk-bridge2.0-0 \
    libatk1.0-0 \
    libatspi2.0-0 \
    libcairo2 \
    libcups2 \
    libdbus-1-3 \
    libdrm2 \
    libgbm1 \
    libglib2.0-0 \
    libgtk-3-0 \
    libnspr4 \
    libnss3 \
    libpango-1.0-0 \
    libpangocairo-1.0-0 \
    libx11-6 \
    libxcb1 \
    libxcomposite1 \
    libxdamage1 \
    libxext6 \
    libxfixes3 \
    libxrandr2 \
    libxrender1 \
    libxshmfence1 \
    && rm -rf /var/lib/apt/lists/*

# Copy and install requirements files first (for better caching)
COPY celery-web-worker/requirements.txt /tmp/web-requirements.txt
COPY shared/requirements-otel.txt /tmp/otel-requirements.txt

# Install Python dependencies with better caching
RUN pip install --no-cache-dir --no-warn-script-location \
    -r /tmp/web-requirements.txt \
    -r /tmp/otel-requirements.txt

# Install Playwright browsers (required by Crawl4AI for web scraping)
# Note: We've already installed all required system dependencies above
# Just download the browser binary (skip install-deps to avoid deprecated font packages)
RUN python -m playwright install chromium

# Step 3: Cleanup build artifacts and caches
RUN apt-get remove -y build-essential && \
    apt-get autoremove -y && \
    apt-get clean && \
    rm -rf /var/lib/apt/lists/* && \
    rm -rf /tmp/* && \
    find /usr/local/lib/python3.11 -type d -name __pycache__ -exec rm -rf {} + 2>/dev/null || true && \
    find /usr/local/lib/python3.11 -type f -name '*.pyc' -delete && \
    find /usr/local -type d -name tests -exec rm -rf {} + 2>/dev/null || true && \
    find /usr/local -type d -name examples -exec rm -rf {} + 2>/dev/null || true

# Copy only required directories (not entire repository)
COPY celery-web-worker /app/celery-web-worker
COPY shared /app/shared

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH="/app"

# Change to service directory and start Celery worker for web_crawling queue
WORKDIR /app/celery-web-worker
CMD ["celery", "-A", "celery_app", "worker", "-Q", "web_crawling", "-l", "info", "-c", "1", "--max-tasks-per-child=100"]
