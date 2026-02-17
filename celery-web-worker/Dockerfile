# Dockerfile for Celery Website Crawling Worker
# Build image: docker build -t knowledgebot-celery-web-worker .
# Run: docker run -e REDIS_URL=redis://redis:6379/1 knowledgebot-celery-web-worker

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
ENV CELERY_BROKER_URL=${REDIS_URL:-redis://localhost:6379/1}
ENV CELERY_RESULT_BACKEND=${REDIS_URL:-redis://localhost:6379/1}

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:5555/api/workers || exit 1

# Default command - web crawling worker
CMD ["celery", "-A", "website_crawling.celery_app", "worker", "-Q", "web_crawling", "-l", "info"]
