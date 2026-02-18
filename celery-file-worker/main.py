"""
File Processing Worker - Celery Mode
The actual work is done by the Celery worker process (celery_app.py + tasks.py).
This file is kept as a stub for compatibility but is NOT the entry point.

Entry point: celery -A celery_app worker -Q file_processing -l info -c 2
"""
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("celery-file-worker", "celery-file-worker")
logger.info("celery-file-worker running in Celery worker mode")
