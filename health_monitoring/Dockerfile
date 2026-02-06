FROM python:3.12-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire backend project
COPY . .

# Install curl for healthcheck
RUN apt-get update && apt-get install -y curl && rm -rf /var/lib/apt/lists/*

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD curl -f http://localhost:${PORT:-8006}/ || exit 1

# Run the service (use PORT env var from Railway, default to 8006 for local dev)
CMD ["sh", "-c", "python -m uvicorn health_monitoring.main:app --host 0.0.0.0 --port ${PORT:-8006}"]
