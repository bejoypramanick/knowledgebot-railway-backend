FROM python:3.12-slim

# Add metadata labels
LABEL maintainer="Knowledge Bot Team"
LABEL description="Configuration Service for Knowledge Bot"
LABEL version="1.0.0"

# Set environment variables for better logging and Python behavior
ENV PYTHONUNBUFFERED=1
ENV PYTHONHASHSEED=random
ENV PIP_NO_CACHE_DIR=1
ENV PIP_DISABLE_PIP_VERSION_CHECK=1
ENV PYTHONPATH="/app"
ENV PYTHONIOENCODING=utf-8

WORKDIR /app

# Log build start
RUN echo "🚀 Starting Configuration Service Docker build..." && \
    echo "📅 Build timestamp: $(date)" && \
    echo "🐳 Using Python: $(python3 --version)"

# Install system dependencies
RUN echo "📦 Installing system dependencies..." && \
    apt-get update && \
    apt-get install -y --no-install-recommends \
    build-essential \
    curl \
    && \
    echo "✅ System dependencies installed" && \
    rm -rf /var/lib/apt/lists/* && \
    echo "🧹 Cleaned up apt cache"

# Copy and install Python dependencies
COPY ../requirements-base.txt ./requirements-base.txt
COPY configuration/requirements.txt ./requirements.txt
RUN echo "🐍 Installing Python dependencies..." && \
    pip install --no-cache-dir -r requirements-base.txt -r requirements.txt && \
    echo "✅ Python dependencies installed"

# Copy application code
COPY configuration/ ./configuration/
COPY ../shared ./shared/
RUN echo "📁 Application code copied"

# Set working directory
WORKDIR /app/configuration

# Create logs directory
RUN mkdir -p /app/logs && \
    echo "📝 Logs directory created"

# Health check
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD sh -c 'curl -f http://localhost:${configuration_PORT:-${PORT:-8004}}/health || exit 1'

# Run the application
CMD ["sh", "-c", "exec uvicorn main:app --host 0.0.0.0 --port ${configuration_PORT:-${PORT:-8004}} --log-level info --access-log"]

