"""
Celery application configuration for Knowledgebase Ingestion Service
Handles async file processing tasks
"""

from celery import Celery
import os
from knowledgebase_ingestion.core.config import settings

# Create Celery app
celery_app = Celery(__name__)

# Configure Celery with Redis broker
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
celery_app.conf.update(
    broker_url=redis_url,
    result_backend=redis_url,
    # Task configuration
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    # Performance tuning for heavy workloads
    worker_prefetch_multiplier=4,
    worker_max_tasks_per_child=1000,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Task routing
    task_routes={
        'knowledgebase_ingestion.tasks.process_file_upload_task': {'queue': 'file_processing'},
    },
    # Result backend configuration
    result_expires=3600,  # Results expire after 1 hour
    # Task timeout (30 minutes for large files)
    task_soft_time_limit=1800,
    task_time_limit=1900,
)

# Auto-discover tasks from tasks.py
celery_app.autodiscover_tasks(['knowledgebase_ingestion'])

@celery_app.task(bind=True)
def debug_task(self):
    """Debug task to verify Celery is working"""
    print(f'Request: {self.request!r}')
