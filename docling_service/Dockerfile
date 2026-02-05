FROM python:3.12-slim

WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1 PYTHONHASHSEED=random PYTHONPATH="/app"

# Install system dependencies for document processing and image handling
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    libgomp1 \
    libgl1-mesa-glx \
    libglib2.0-0 \
    libsm6 \
    libxext6 \
    libxrender-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements and install
COPY docling_service/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY shared/ ./shared/
COPY docling_service/ ./docling_service/

# Set working directory
WORKDIR /app/docling_service

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=120s --retries=5 \
    CMD sh -c 'curl -f http://localhost:${DOCLING_PORT:-${PORT:-8004}}/health || exit 1'

# Run the application
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${DOCLING_PORT:-${PORT:-8004}} --log-level debug --access-log"]
