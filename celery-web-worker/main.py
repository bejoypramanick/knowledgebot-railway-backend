"""
Website Crawling Worker - Celery Mode
The actual work is done by the Celery worker process (celery_app.py + tasks.py).
This file is kept as a stub for compatibility but is NOT the entry point.

Entry point: celery -A celery_app worker -Q web_crawling -l info -c 1
"""
from shared.telemetry import setup_telemetry, instrument_fastapi
from shared.otel_logger import get_otel_logger

# Initialize telemetry BEFORE creating any loggers
setup_telemetry("celery-web-worker")

logger = get_otel_logger("celery-web-worker", "celery-web-worker")
logger.info("celery-web-worker running in Celery worker mode")
