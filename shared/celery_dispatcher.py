"""
Celery Dispatcher for Knowledgebase Ingestion Service
Used to dispatch tasks to workers without importing worker code directly.
"""
import os
from celery import Celery
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("celery_dispatcher", "knowledgebase-ingestion")

# File processing: Redis DB 0 (EXPLICIT - never falls back to REDIS_URL)
# Must be explicitly configured via FILE_REDIS_URL environment variable
file_redis_url = os.getenv('FILE_REDIS_URL')
if not file_redis_url:
    logger.warning("⚠️  FILE_REDIS_URL not set - file Celery dispatcher will fail")

# Web crawling: Redis DB 1 (EXPLICIT - never falls back to REDIS_URL)
# Must be explicitly configured via WEB_REDIS_URL environment variable
web_redis_url = os.getenv('WEB_REDIS_URL')
if not web_redis_url:
    logger.warning("⚠️  WEB_REDIS_URL not set - web Celery dispatcher will fail")

logger.info("=" * 80)
logger.info("🚀 [CELERY_DISPATCHER_INIT] Initializing Celery Dispatcher")
logger.info("=" * 80)
logger.info(f"🔑 [ENV_VAR] FILE_REDIS_URL: {os.getenv('FILE_REDIS_URL', 'NOT SET (using default)')}")
logger.info(f"🔑 [ENV_VAR] WEB_REDIS_URL: {os.getenv('WEB_REDIS_URL', 'NOT SET (using default)')}")
logger.info(f"🔑 [ENV_VAR] REDIS_URL: {os.getenv('REDIS_URL', 'NOT SET')}")
logger.info(f"📍 [FILE_REDIS_RESOLVED] URL: {file_redis_url}")
logger.info(f"📍 [WEB_REDIS_RESOLVED] URL: {web_redis_url}")

# Dispatcher app for file processing tasks (DB 0)
logger.info("🔧 [FILE_CELERY] Creating file_celery dispatcher...")
file_celery = Celery('file_dispatcher', broker=file_redis_url)
file_celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    result_backend=file_redis_url,
)
logger.info("✅ [FILE_CELERY] file_celery dispatcher created successfully")

# Dispatcher app for web crawling tasks (DB 1)
logger.info("🔧 [WEB_CELERY] Creating web_celery dispatcher...")
web_celery = Celery('web_dispatcher', broker=web_redis_url)
web_celery.conf.update(
    task_serializer='json',
    accept_content=['json'],
    result_serializer='json',
    result_backend=web_redis_url,
)
logger.info("✅ [WEB_CELERY] web_celery dispatcher created successfully")

# Test Redis connectivity at import time
logger.info("🔍 [REDIS_TEST] Testing Redis connectivity...")
try:
    import redis

    # Test file Redis
    try:
        file_redis = redis.from_url(file_redis_url, decode_responses=True, socket_connect_timeout=5)
        file_redis.ping()
        logger.info("✅ [FILE_REDIS_TEST] File Redis connection successful")
        file_redis.close()
    except Exception as e:
        logger.warning(f"⚠️  [FILE_REDIS_TEST] File Redis connection failed: {e}")

    # Test web Redis
    try:
        web_redis = redis.from_url(web_redis_url, decode_responses=True, socket_connect_timeout=5)
        web_redis.ping()
        logger.info("✅ [WEB_REDIS_TEST] Web Redis connection successful")
        web_redis.close()
    except Exception as e:
        logger.warning(f"⚠️  [WEB_REDIS_TEST] Web Redis connection failed: {e}")
except Exception as e:
    logger.error(f"❌ [REDIS_TEST] Error testing Redis connectivity: {e}")

logger.info("=" * 80)
logger.info("✅ [CELERY_DISPATCHER_INIT] Celery Dispatcher initialization complete")
logger.info("=" * 80)

# Add methods to log when tasks are sent
original_send_task = web_celery.send_task

def logged_send_task(*args, **kwargs):
    """Wrapper to log all send_task calls"""
    logger.info("=" * 80)
    logger.info("📤 [WEB_CELERY_SEND_TASK] web_celery.send_task() called")
    logger.info("=" * 80)
    logger.info(f"   Args: {args}")
    logger.info(f"   Kwargs: {kwargs}")
    try:
        result = original_send_task(*args, **kwargs)
        logger.info(f"✅ [WEB_CELERY_SEND_RESULT] Task sent successfully")
        logger.info(f"   Result type: {type(result)}")
        logger.info(f"   Result ID: {result.id if hasattr(result, 'id') else 'N/A'}")
        return result
    except Exception as e:
        logger.error(f"❌ [WEB_CELERY_SEND_ERROR] send_task failed: {e}", exc_info=True)
        raise

web_celery.send_task = logged_send_task
logger.info("✅ [SEND_TASK_WRAPPER] Wrapped web_celery.send_task with logging")
