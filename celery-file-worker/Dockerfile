# Dockerfile for Celery File Processing Worker
# Optimized for minimal image size by copying only required directories
# Build image: docker build -t knowledgebot-celery-file-worker .
# Run: docker run -e REDIS_URL=redis://redis:6379/0 knowledgebot-celery-file-worker
# Updated: 2026-02-20 - Added google-generativeai package

FROM python:3.11-slim

WORKDIR /app

# Install system dependencies (minimal - no browser tools needed)
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    postgresql-client \
    && rm -rf /var/lib/apt/lists/*

# Copy and install requirements files first (for better caching)
COPY celery-file-worker/requirements.txt /tmp/kb-requirements.txt
COPY shared/requirements-otel.txt /tmp/otel-requirements.txt

# Install Python dependencies with better caching
RUN pip install --no-cache-dir --no-warn-script-location \
    -r /tmp/kb-requirements.txt \
    -r /tmp/otel-requirements.txt

# Copy only required directories (not entire repository)
COPY celery-file-worker /app/celery-file-worker
COPY shared /app/shared

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV PYTHONPATH="/app"

# Change to service directory and start Celery worker for file_processing queue
WORKDIR /app/celery-file-worker
CMD ["celery", "-A", "celery_app", "worker", "-Q", "file_processing", "-l", "info", "-c", "4", "--max-tasks-per-child=1000"]
