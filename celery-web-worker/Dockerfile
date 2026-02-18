# Dockerfile for Celery Website Crawling Worker
# Build image: docker build -t knowledgebot-celery-web-worker .
# Run: docker run -e REDIS_URL=redis://redis:6379/1 knowledgebot-celery-web-worker
# Build: 2025-02-18 - Celery worker with asyncio.run() fix

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    build-essential \
    curl \
    git \
    postgresql-client \
    chromium \
    chromium-driver \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements files
COPY celery-web-worker/requirements.txt /tmp/web-requirements.txt
COPY shared/requirements-otel.txt /tmp/otel-requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r /tmp/web-requirements.txt && \
    pip install --no-cache-dir -r /tmp/otel-requirements.txt

# Install Playwright browsers (required for Crawl4AI)
# Use pip to run playwright install to ensure it's found
RUN pip install playwright && python -m playwright install chromium --with-deps

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
# PYTHONPATH includes /app so 'shared.*' imports work from /app/celery-web-worker/
ENV PYTHONPATH="/app"
# Note: REDIS_URL is set at runtime via Railway environment variables
# Do NOT set CELERY_BROKER_URL/CELERY_RESULT_BACKEND here - let celery_app.py read REDIS_URL at runtime

# Change to service directory and start Celery worker for web_crawling queue
WORKDIR /app/celery-web-worker
CMD ["celery", "-A", "celery_app", "worker", "-Q", "web_crawling", "-l", "info", "-c", "1", "--max-tasks-per-child=100"]
