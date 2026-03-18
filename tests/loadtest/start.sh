#!/bin/bash

# Start script for Railway deployment
echo "🚀 Starting Locust Load Test Server on Railway"
echo "Target: ${TARGET_HOST:-https://api-gateway-common.up.railway.app}"
echo "Port: ${PORT:-8080}"
echo "Web Host: ${LOCUST_WEB_HOST:-0.0.0.0}"

# Start Locust with Railway-specific configuration
exec locust \
    -f locustfile.py \
    --host="${TARGET_HOST:-https://api-gateway-common.up.railway.app}" \
    --web-host="${LOCUST_WEB_HOST:-0.0.0.0}" \
    --web-port="${PORT:-8080}" \
    --logfile=/tmp/locust.log \
    --loglevel=INFO