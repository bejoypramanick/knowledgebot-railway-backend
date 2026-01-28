FROM mcr.microsoft.com/playwright/python:v1.57.0-noble

WORKDIR /app

# Set environment variables
ENV PYTHONUNBUFFERED=1

# Install dependencies
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    && rm -rf /var/lib/apt/lists/*

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

# Copy application code
COPY services/website_scraping/ ./services/website_scraping/
COPY shared ./shared/

# Set working directory
WORKDIR /app/services/website_scraping

# Set the PYTHONPATH environment variable to include the /app directory
ENV PYTHONPATH="/app"

# Update health check to use the `/health` endpoint
# More forgiving start-period to account for cold starts and heavy startup tasks
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD sh -c 'curl -f http://localhost:${WEBSITE_SCRAPING_PORT:-${PORT:-8002}}/health || exit 1'

# Run the application with uvicorn - prefer WEBSITE_SCRAPING_PORT, else PORT, else default 8002
# Enable debug log level and access logs for better visibility
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${WEBSITE_SCRAPING_PORT:-${PORT:-8002}} --log-level debug --access-log"]
