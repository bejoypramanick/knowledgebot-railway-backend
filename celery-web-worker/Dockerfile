# Dockerfile for Celery Website Crawling Worker
# Optimized for minimal image size by copying only required directories
# Build image: docker build -t knowledgebot-celery-web-worker .
# Run: docker run -e REDIS_URL=redis://redis:6379/1 knowledgebot-celery-web-worker

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
# Playwright requires these system libraries to run chromium
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    postgresql-client \
    ca-certificates \
    fonts-liberation \
    fonts-noto-cjk \
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
    libgtk-4-1 \
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
    xdg-utils \
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
