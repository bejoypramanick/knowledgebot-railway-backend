"""
Celery application configuration for Website Crawling Worker
Handles async website scraping and crawling tasks
"""

from celery import Celery
from celery.signals import before_task_publish, task_prerun, task_postrun, task_failure, task_retry
from shared.otel_logger import get_otel_logger
import os
import redis

logger = get_otel_logger("celery_app", "celery-web-worker")

# Configure Celery with Redis broker (DB 1)
# Use explicit fallback to avoid cross-DB issues
redis_url = os.getenv('WEB_REDIS_URL')

# Create Celery app
celery_app = Celery('celery_web_worker')

# Log Celery initialization
logger.info("🚀 [CELERY_APP] Initializing Celery for Website Crawling Worker")
logger.info(f"📊 [REDIS] WEB_REDIS_URL: {redis_url}")

# Test Redis connection at startup and monitor queue
try:
    redis_client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
    redis_client.ping()
    logger.info("✅ [REDIS] Connection test successful - Redis is reachable")

    # Check queue depth
    queue_depth = redis_client.llen('web_crawling')
    logger.info(f"📊 [REDIS] Current queue depth: {queue_depth} tasks")

    # Check if there are any tasks in the queue
    if queue_depth > 0:
        sample_tasks = redis_client.lrange('web_crawling', 0, 2)
        logger.info(f"📋 [REDIS] Sample tasks in queue: {sample_tasks}")

    redis_client.close()
except redis.ConnectionError as conn_err:
    logger.warning(f"⚠️  [REDIS] Connection test failed (this is OK in local dev): {redis_url}")
    logger.debug(f"   Error: {conn_err}")
except Exception as e:
    logger.error(f"❌ [REDIS] Unexpected error during connection test: {e}")

celery_app.conf.update(
    broker_url=redis_url,
    result_backend=redis_url,
    # Task configuration
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    # Performance tuning for web crawling (lower prefetch, fewer concurrent)
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=100,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Task routing
    task_routes={
        'tasks.scrape_website_task': {'queue': 'web_crawling'},
    },
    # Result backend configuration
    result_expires=3600,  # Results expire after 1 hour
    # Task timeout (6 hours for web crawling - enough for 100+ pages at 5MB limit)
    task_soft_time_limit=21600,  # 6 hours
    task_time_limit=21700,  # 6 hours + 100s buffer
)

logger.info("✅ [CELERY_APP] Configuration updated - Task timeout: 6 hours, Queue: 'web_crawling'")

# Import tasks module to register task definitions
try:
    import tasks  # noqa: F401
    logger.info("✅ [CELERY_APP] Tasks module loaded successfully")
except ImportError as e:
    logger.error(f"❌ [CELERY_APP] Failed to load tasks module: {e}")


# Signal handlers for task lifecycle monitoring
@before_task_publish.connect(sender='tasks.scrape_website_task')
def before_task_publish_handler(sender=None, body=None, **kwargs):
    """Log before task is published to Redis queue"""
    try:
        task_args = body.get('args', []) if isinstance(body, dict) else []
        website_id = task_args[0] if task_args else 'unknown'
        logger.info(f"📤 [TASK_PUBLISH] Before publishing: {sender} - Website ID: {website_id}")
    except Exception as e:
        logger.error(f"❌ [TASK_PUBLISH] Error in pre-publish handler: {e}")


@task_prerun.connect(sender='tasks.scrape_website_task')
def task_prerun_handler(sender=None, task_id=None, args=None, **kwargs):
    """Log when task starts execution"""
    try:
        website_id = args[0] if args else 'unknown'
        logger.info(f"⏱️  [TASK_PRERUN] Task starting execution - Task ID: {task_id}, Website ID: {website_id}")
    except Exception as e:
        logger.error(f"❌ [TASK_PRERUN] Error in pre-run handler: {e}")


@task_postrun.connect(sender='tasks.scrape_website_task')
def task_postrun_handler(sender=None, task_id=None, args=None, **kwargs):
    """Log when task completes successfully"""
    try:
        website_id = args[0] if args else 'unknown'
        logger.info(f"✅ [TASK_POSTRUN] Task completed successfully - Task ID: {task_id}, Website ID: {website_id}")
    except Exception as e:
        logger.error(f"❌ [TASK_POSTRUN] Error in post-run handler: {e}")


@task_failure.connect(sender='tasks.scrape_website_task')
def task_failure_handler(sender=None, task_id=None, args=None, exception=None, **kwargs):
    """Log when task fails"""
    try:
        website_id = args[0] if args else 'unknown'
        logger.error(f"❌ [TASK_FAILURE] Task failed - Task ID: {task_id}, Website ID: {website_id}, Exception: {exception}")
    except Exception as e:
        logger.error(f"❌ [TASK_FAILURE] Error in failure handler: {e}")


@task_retry.connect(sender='tasks.scrape_website_task')
def task_retry_handler(sender=None, task_id=None, args=None, reason=None, **kwargs):
    """Log when task is retried"""
    try:
        website_id = args[0] if args else 'unknown'
        logger.warning(f"🔄 [TASK_RETRY] Task retrying - Task ID: {task_id}, Website ID: {website_id}, Reason: {reason}")
    except Exception as e:
        logger.error(f"❌ [TASK_RETRY] Error in retry handler: {e}")


@celery_app.task(bind=True)
def debug_task(self):
    """Debug task to verify Celery is working"""
    logger.info(f"🧪 [DEBUG_TASK] Debug task invoked - Task ID: {self.request.id}")
    print(f'Request: {self.request!r}')


# Keep-alive heartbeat to ensure worker stays running
def start_heartbeat():
    """Start a background heartbeat to keep worker alive"""
    import threading
    import time

    def heartbeat():
        logger.info("❤️  [HEARTBEAT_START] Worker heartbeat monitor started")
        while True:
            try:
                time.sleep(30)  # Log every 30 seconds
                import redis
                r = redis.from_url(redis_url, decode_responses=True)
                queue_len = r.llen('web_crawling')
                r.close()
                logger.info(f"❤️  [HEARTBEAT] Worker alive - Queue depth: {queue_len} tasks")
            except Exception as e:
                logger.warning(f"⚠️  [HEARTBEAT] Error in heartbeat: {e}")

    thread = threading.Thread(target=heartbeat, daemon=True)
    thread.start()
    logger.info("✅ [HEARTBEAT] Heartbeat thread started (daemon)")


# Start heartbeat when app is imported
try:
    start_heartbeat()
except Exception as e:
    logger.warning(f"⚠️  [HEARTBEAT] Could not start heartbeat: {e}")
