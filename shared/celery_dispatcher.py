"""
Celery Dispatcher for Knowledgebase Ingestion Service
Used to dispatch tasks to workers without importing worker code directly.
"""
import os
from celery import Celery
from urllib.parse import urlparse, urlunparse
from shared.otel_logger import get_otel_logger
from shared.redis_factory import resolve_redis_url

logger = get_otel_logger("celery_dispatcher", "knowledgebase-ingestion")


def _redact_redis_url(redis_url: str) -> str:
    """Redact sensitive info (password) from Redis URL for logging."""
    if not redis_url:
        return redis_url
    try:
        parsed = urlparse(redis_url)
        # Redact password if present
        if parsed.password:
            netloc = f"{parsed.username}:***@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            redacted = urlunparse((
                parsed.scheme,
                netloc,
                parsed.path,
                parsed.params,
                parsed.query,
                parsed.fragment
            ))
            return redacted
        return redis_url
    except Exception:
        # If parsing fails, return original
        return redis_url


file_redis_url = resolve_redis_url(
    primary_env_var='file_task_queue',
    db_env_var='FILE_TASK_QUEUE_REDIS_DB',
    default_db=0,
)
web_redis_url = resolve_redis_url(
    primary_env_var='web_task_queue',
    db_env_var='WEB_TASK_QUEUE_REDIS_DB',
    default_db=1,
)

logger.info("=" * 80)
logger.info("🚀 [CELERY_DISPATCHER_INIT] Initializing Celery Dispatcher")
logger.info("=" * 80)
logger.info(f"🔑 [ENV_VAR] REDIS_URL: {'SET' if os.getenv('REDIS_URL') else 'NOT SET'}")
logger.info(f"🔑 [ENV_VAR] FILE_TASK_QUEUE_REDIS_DB: {os.getenv('FILE_TASK_QUEUE_REDIS_DB', '0')}")
logger.info(f"🔑 [ENV_VAR] WEB_TASK_QUEUE_REDIS_DB: {os.getenv('WEB_TASK_QUEUE_REDIS_DB', '1')}")
logger.info(f"📍 [FILE_REDIS_RESOLVED] URL: {_redact_redis_url(file_redis_url)}")
logger.info(f"📍 [WEB_REDIS_RESOLVED] URL: {_redact_redis_url(web_redis_url)}")

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

def _redact_crawler_payload(value):
    """Avoid logging custom crawl cookies or headers in Celery payloads."""
    if isinstance(value, dict):
        redacted = {k: _redact_crawler_payload(v) for k, v in value.items()}
        if redacted.get("crawler_cookies"):
            redacted["crawler_cookies"] = "[redacted]"
        if redacted.get("crawler_headers"):
            redacted["crawler_headers"] = "[redacted]"
        return redacted
    if isinstance(value, list):
        return [_redact_crawler_payload(item) for item in value]
    if isinstance(value, tuple):
        return tuple(_redact_crawler_payload(item) for item in value)
    return value

def logged_send_task(*args, **kwargs):
    """Wrapper to log all send_task calls"""
    logger.info("=" * 80)
    logger.info("📤 [WEB_CELERY_SEND_TASK] web_celery.send_task() called")
    logger.info("=" * 80)
    logger.info(f"   Args: {_redact_crawler_payload(args)}")
    logger.info(f"   Kwargs: {_redact_crawler_payload(kwargs)}")
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
