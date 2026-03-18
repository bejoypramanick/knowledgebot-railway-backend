FROM python:3.11-slim

# Set working directory
WORKDIR /app

# Install system dependencies
RUN apt-get update && apt-get install -y \
    gcc \
    && rm -rf /var/lib/apt/lists/*

# Copy requirements first for better caching
COPY requirements.txt .

# Install Python dependencies
RUN pip install --no-cache-dir -r requirements.txt

# Copy application files
COPY . .

# Expose port for Locust web UI
EXPOSE 8080

# Default command - can be overridden by Railway
CMD ["locust", "-f", "locustfile.py", "--host=https://api-gateway-common.up.railway.app", "--web-host=0.0.0.0", "--web-port=8080"]