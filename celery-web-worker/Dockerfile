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
COPY celery-web-worker/requirements.txt /tmp/web-requirements.txt
COPY shared/requirements-otel.txt /tmp/otel-requirements.txt

# Install Python dependencies
RUN pip install --no-cache-dir -r /tmp/web-requirements.txt && \
    pip install --no-cache-dir -r /tmp/otel-requirements.txt

# Install Playwright browsers (required for Crawl4AI)
# Ensure Python scripts are in PATH and install browsers
ENV PATH="/root/.local/bin:$PATH"
RUN python -m playwright install chromium --with-deps

# Copy application code
COPY . .

# Set environment variables
ENV PYTHONUNBUFFERED=1
# Note: REDIS_URL is set at runtime via Railway environment variables
# Do NOT set CELERY_BROKER_URL/CELERY_RESULT_BACKEND here - let celery_app.py read REDIS_URL at runtime

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=40s --retries=3 \
    CMD curl -f http://localhost:8080/health || exit 1

# Default command - FastAPI server with Redis polling loop
CMD ["uvicorn", "main:app", "--host", "0.0.0.0", "--port", "8080"]
