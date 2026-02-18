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
COPY celery-file-worker/requirements.txt /tmp/kb-requirements.txt
COPY shared/requirements-otel.txt /tmp/otel-requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r /tmp/kb-requirements.txt && \
    pip install --no-cache-dir -r /tmp/otel-requirements.txt

# Install Playwright browsers (may be needed by docling or other services)
RUN playwright install chromium

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
# Note: REDIS_URL is set at runtime via Railway environment variables
# Do NOT set CELERY_BROKER_URL/CELERY_RESULT_BACKEND here - let celery_app.py read REDIS_URL at runtime

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5555/api/workers || exit 1

# Default command - file processing worker
CMD ["celery", "-A", "knowledgebase_ingestion.celery_app", "worker", "-Q", "file_processing", "-l", "info"]
