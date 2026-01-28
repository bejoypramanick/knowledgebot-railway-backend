FROM python:3.11-slim

WORKDIR /app

# Build Stage 1: System Dependencies
RUN echo "🛠️ --- Installing System Packages ---"
RUN apt-get update && apt-get install -y --no-install-recommends \
    build-essential \
    libxml2-dev \
    libxslt1-dev \
    curl \
    && rm -rf /var/lib/apt/lists/*
RUN echo "✅ System Packages installed successfully"

# Build Stage 2: Python Dependencies
RUN echo "🐍 --- Installing Python Dependencies ---"
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt
RUN echo "📦 --- Installed Python Packages ---"
RUN pip list
RUN echo "✅ Python Dependencies installed successfully"

# Build Stage 3: Application Code
RUN echo "📂 --- Copying Application Code ---"
COPY services/chatbot_orchestration/ ./services/chatbot_orchestration/
COPY shared ./shared/
RUN echo "✅ Code copied"

# Set working directory and environment
WORKDIR /app/services/chatbot_orchestration
ENV PYTHONPATH="/app"
ENV PYTHONUNBUFFERED=1

RUN echo "🧐 --- Final Container Structure ---"
RUN ls -R /app

# Update health check to use the `/health` endpoint
HEALTHCHECK --interval=30s --timeout=10s --start-period=60s --retries=5 \
    CMD sh -c 'curl -f http://localhost:${CHATBOT_ORCH_PORT:-${PORT:-8003}}/health || exit 1'

# Expose default port
EXPOSE 8003

# Run the application with uvicorn - prefer CHATBOT_ORCH_PORT, else PORT, else default 8003
RUN echo "🚀 --- Final Build Complete ---"
CMD ["sh", "-c", "echo '🌐 Runtime Port Check: CHATBOT_ORCH_PORT='${CHATBOT_ORCH_PORT}' PORT='${PORT}; exec uvicorn main:app --host 0.0.0.0 --port ${CHATBOT_ORCH_PORT:-${PORT:-8003}} --log-level debug --access-log"]
