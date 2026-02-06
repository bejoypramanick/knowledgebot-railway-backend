FROM python:3.12-slim

WORKDIR /app

# Copy requirements and install dependencies
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy the entire backend project
COPY . .

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=5s --retries=3 \
    CMD python -c "import httpx; httpx.get('http://localhost:8006/api/v1/health/health')" || exit 1

# Run the service
CMD ["python", "-m", "uvicorn", "health_monitoring.main:app", "--host", "0.0.0.0", "--port", "8006"]
