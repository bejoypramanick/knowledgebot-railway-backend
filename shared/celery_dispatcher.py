"""
Celery Dispatcher for Knowledgebase Ingestion Service
Used to dispatch tasks to workers without importing worker code directly.
"""
import os
from celery import Celery
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("celery_dispatcher", "knowledgebase-ingestion")

# File processing: Redis DB 0
file_redis_url = os.getenv('FILE_REDIS_URL', os.getenv('REDIS_URL', 'redis://localhost:6379/0'))

# Web crawling: Redis DB 1
web_redis_url = os.getenv('WEB_REDIS_URL', os.getenv('REDIS_URL', 'redis://localhost:6379/1'))

logger.info("=" * 80)
logger.info("🚀 [CELERY_DISPATCHER_INIT] Initializing Celery Dispatcher")
logger.info("=" * 80)
logger.info(f"📍 [FILE_REDIS] URL: {file_redis_url}")
logger.info(f"📍 [WEB_REDIS] URL: {web_redis_url}")

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
