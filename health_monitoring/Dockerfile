FROM python:3.12-slim

WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Copy requirements and install dependencies
# Note: Build context is parent directory due to rootDirectory = ".." in railway.toml
COPY health_monitoring/requirements.txt ./requirements.txt
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY shared/ ./shared/
COPY health_monitoring/ ./health_monitoring/

# Set working directory
WORKDIR /app/health_monitoring

# Install curl for healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Set the PYTHONPATH environment variable to include the /app directory
ENV PYTHONPATH="/app"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=10s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8006}/health || exit 1

# Run the service (use PORT env var from Railway, default to 8006 for local dev)
CMD ["sh", "-c", "python -m uvicorn main:app --host 0.0.0.0 --port ${PORT:-8006}"]
