"""
Celery application configuration for File Processing Worker
Handles async file processing tasks
"""

from celery import Celery
from celery.signals import before_task_publish, task_prerun, task_postrun, task_failure, task_retry
from shared.otel_logger import get_otel_logger
import os
import redis

logger = get_otel_logger("celery_app", "celery-file-worker")

# Configure Celery with Redis broker (DB 0)
# Must be explicitly configured via FILE_REDIS_URL environment variable
redis_url = os.getenv('FILE_REDIS_URL')

# Create Celery app
celery_app = Celery('celery_file_worker')

# Log Celery initialization
logger.info("🚀 [CELERY_APP] Initializing Celery for File Processing Worker")
logger.info(f"📊 [REDIS] FILE_REDIS_URL: {redis_url}")

if not redis_url:
    logger.warning("⚠️  FILE_REDIS_URL not set - file Celery app will fail to connect to Redis")

# Test Redis connection at startup
try:
    redis_client = redis.from_url(redis_url, decode_responses=True, socket_connect_timeout=2)
    redis_client.ping()
    logger.info("✅ [REDIS] Connection test successful - Redis is reachable")
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
    # Performance tuning for heavy workloads
    worker_prefetch_multiplier=1,
    worker_max_tasks_per_child=1000,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    # Task routing
    task_routes={
        'tasks.process_file_upload_task': {'queue': 'file_processing'},
    },
    # Result backend configuration
    result_expires=3600,  # Results expire after 1 hour
    # Task timeout (1 hour for 5MB file processing with docling + Gemini upload)
    task_soft_time_limit=3600,  # 1 hour
    task_time_limit=3700,  # 1 hour + 100s buffer
)

logger.info("✅ [CELERY_APP] Configuration updated - Task timeout: 1 hour, Queue: 'file_processing'")

# Import tasks module to register task definitions
try:
    import tasks  # noqa: F401
    logger.info("✅ [CELERY_APP] Tasks module loaded successfully")
except ImportError as e:
    logger.error(f"❌ [CELERY_APP] Failed to load tasks module: {e}")


# Signal handlers for task lifecycle monitoring
@before_task_publish.connect(sender='tasks.process_file_upload_task')
def before_task_publish_handler(sender=None, body=None, **kwargs):
    """Log before task is published to Redis queue"""
    try:
        task_args = body.get('args', []) if isinstance(body, dict) else []
        filename = task_args[0] if task_args else 'unknown'
        logger.info(f"📤 [TASK_PUBLISH] Before publishing: {sender} - File: {filename}")
    except Exception as e:
        logger.error(f"❌ [TASK_PUBLISH] Error in pre-publish handler: {e}")


@task_prerun.connect(sender='tasks.process_file_upload_task')
def task_prerun_handler(sender=None, task_id=None, args=None, **kwargs):
    """Log when task starts execution"""
    try:
        filename = args[0] if args else 'unknown'
        logger.info(f"⏱️  [TASK_PRERUN] Task starting execution - Task ID: {task_id}, File: {filename}")
    except Exception as e:
        logger.error(f"❌ [TASK_PRERUN] Error in pre-run handler: {e}")


@task_postrun.connect(sender='tasks.process_file_upload_task')
def task_postrun_handler(sender=None, task_id=None, args=None, **kwargs):
    """Log when task completes successfully"""
    try:
        filename = args[0] if args else 'unknown'
        logger.info(f"✅ [TASK_POSTRUN] Task completed successfully - Task ID: {task_id}, File: {filename}")
    except Exception as e:
        logger.error(f"❌ [TASK_POSTRUN] Error in post-run handler: {e}")


@task_failure.connect(sender='tasks.process_file_upload_task')
def task_failure_handler(sender=None, task_id=None, args=None, exception=None, **kwargs):
    """Log when task fails"""
    try:
        filename = args[0] if args else 'unknown'
        logger.error(f"❌ [TASK_FAILURE] Task failed - Task ID: {task_id}, File: {filename}, Exception: {exception}")
    except Exception as e:
        logger.error(f"❌ [TASK_FAILURE] Error in failure handler: {e}")


@task_retry.connect(sender='tasks.process_file_upload_task')
def task_retry_handler(sender=None, task_id=None, args=None, reason=None, **kwargs):
    """Log when task is retried"""
    try:
        filename = args[0] if args else 'unknown'
        logger.warning(f"🔄 [TASK_RETRY] Task retrying - Task ID: {task_id}, File: {filename}, Reason: {reason}")
    except Exception as e:
        logger.error(f"❌ [TASK_RETRY] Error in retry handler: {e}")


@celery_app.task(bind=True)
def debug_task(self):
    """Debug task to verify Celery is working"""
    logger.info(f"🧪 [DEBUG_TASK] Debug task invoked - Task ID: {self.request.id}")
    print(f'Request: {self.request!r}')
