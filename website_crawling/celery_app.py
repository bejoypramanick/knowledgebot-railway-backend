"""
Celery application configuration for Website Crawling Service
Handles async website scraping and crawling tasks
"""

from celery import Celery
import os

# Create Celery app
celery_app = Celery(__name__)

# Configure Celery with Redis broker
redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/1')
celery_app.conf.update(
    broker_url=redis_url,
    result_backend=redis_url,
    # Task configuration
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    # Performance tuning for heavy workloads (web crawling)
    worker_prefetch_multiplier=2,  # Lower prefetch for web crawling
    worker_max_tasks_per_child=100,  # Restart worker after 100 tasks
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Task routing
    task_routes={
        'website_crawling.tasks.scrape_website_task': {'queue': 'web_crawling'},
    },
    # Result backend configuration
    result_expires=3600,  # Results expire after 1 hour
    # Task timeout (2 hours for large sitemaps)
    task_soft_time_limit=7200,
    task_time_limit=7300,
)

# Auto-discover tasks from tasks.py
celery_app.autodiscover_tasks(['website_crawling'])

@celery_app.task(bind=True)
def debug_task(self):
    """Debug task to verify Celery is working"""
    print(f'Request: {self.request!r}')
