# Dockerfile for Celery File Processing Worker
# Build image: docker build -t knowledgebot-celery-file-worker .
# Run: docker run -e REDIS_URL=redis://redis:6379/0 knowledgebot-celery-file-worker

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
COPY knowledgebase_ingestion/requirements.txt /tmp/kb-requirements.txt
COPY website_crawling/requirements.txt /tmp/web-requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r /tmp/kb-requirements.txt && \
    pip install --no-cache-dir -r /tmp/web-requirements.txt

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
ENV CELERY_BROKER_URL=${REDIS_URL:-redis://localhost:6379/0}
ENV CELERY_RESULT_BACKEND=${REDIS_URL:-redis://localhost:6379/0}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5555/api/workers || exit 1

# Default command - file processing worker
CMD ["celery", "-A", "knowledgebase_ingestion.celery_app", "worker", "-Q", "file_processing", "-l", "info"]
