"""
Celery application configuration for File Processing Worker
Handles async file processing tasks
"""

import sys
import os

# Ensure celery-file-worker directory is in Python path for module imports
current_dir = os.path.dirname(os.path.abspath(__file__))
if current_dir not in sys.path:
    sys.path.insert(0, current_dir)

from celery import Celery
from celery.signals import before_task_publish, task_prerun, task_postrun, task_failure, task_retry, worker_process_init
from shared.otel_logger import get_otel_logger
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

# Get concurrency from environment variable with default of 10 for gevent pool
worker_concurrency = int(os.getenv('CELERY_FILE_CONCURRENCY', '10'))

celery_app.conf.update(
    broker_url=redis_url,
    result_backend=redis_url,
    # Task configuration
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    timezone='UTC',
    enable_utc=True,
    # Performance tuning for file processing
    # Concurrency is configurable via CELERY_FILE_CONCURRENCY environment variable
    worker_prefetch_multiplier=1,  # Each worker prefetches only 1 task
    worker_max_tasks_per_child=100,  # Restart worker after 100 tasks to prevent memory leaks
    worker_concurrency=worker_concurrency,  # Parallel greenlets (configurable)
    task_acks_late=True,  # Acknowledge task only after completion
    task_reject_on_worker_lost=True,  # Requeue task if worker dies
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

logger.info("✅ [CELERY_APP] Configuration updated")
logger.info(f"   Concurrency: {worker_concurrency} parallel workers")
logger.info(f"   Prefetch: 1 task per worker")
logger.info(f"   Task timeout: 1 hour")
logger.info(f"   Queue: 'file_processing'")

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


@worker_process_init.connect
def init_worker_process(**kwargs):
    """
    Initialize database pool after worker process fork.
    
    This is critical for Celery prefork pool workers. When the parent process forks,
    file descriptors (including database connections) are copied to child processes,
    causing conflicts. We must close any inherited pools and create fresh ones.
    """
    logger.info("🔄 [WORKER_INIT] Worker process initializing after fork")
    
    try:
        import asyncio
        import gc
        
        # Close any inherited event loop FIRST to prevent file descriptor conflicts
        try:
            loop = asyncio.get_event_loop()
            if loop and not loop.is_closed():
                logger.info("🔄 [WORKER_INIT] Closing inherited event loop")
                # Cancel all pending tasks
                pending = asyncio.all_tasks(loop)
                for task in pending:
                    task.cancel()
                # Close the loop
                loop.stop()
                loop.close()
        except RuntimeError:
            # No event loop in current thread - this is fine
            pass
        
        # Set a new event loop for this worker
        new_loop = asyncio.new_event_loop()
        asyncio.set_event_loop(new_loop)
        logger.info("✅ [WORKER_INIT] Created fresh event loop for worker process")
        
        # Now handle database pool
        from shared.db import DatabaseManager
        
        # Reset the singleton instance to force recreation
        if DatabaseManager._instance:
            logger.warning("⚠️ [WORKER_INIT] Found inherited DatabaseManager instance from parent process")
            
            # Try to close the pool gracefully if it exists
            if DatabaseManager._instance._pool:
                try:
                    # Don't use async close - just terminate the pool
                    # The pool is from the parent process and shouldn't be used anyway
                    DatabaseManager._instance._pool.terminate()
                    logger.info("✅ [WORKER_INIT] Terminated inherited database pool")
                except Exception as e:
                    logger.warning(f"⚠️ [WORKER_INIT] Error terminating inherited pool: {e}")
            
            # Reset the singleton to None so it will be recreated
            DatabaseManager._instance = None
            logger.info("✅ [WORKER_INIT] Reset DatabaseManager singleton, will create fresh instance on first use")
        else:
            logger.info("✅ [WORKER_INIT] No inherited DatabaseManager found")
        
        # Force garbage collection to clean up any lingering file descriptors
        gc.collect()
        logger.info("✅ [WORKER_INIT] Worker process initialization complete")
            
    except Exception as e:
        logger.error(f"❌ [WORKER_INIT] Error during worker initialization: {e}")
        import traceback
        logger.error(f"   Traceback: {traceback.format_exc()}")


@celery_app.task(bind=True)
def debug_task(self):
    """Debug task to verify Celery is working"""
    logger.info(f"🧪 [DEBUG_TASK] Debug task invoked - Task ID: {self.request.id}")
    print(f'Request: {self.request!r}')
