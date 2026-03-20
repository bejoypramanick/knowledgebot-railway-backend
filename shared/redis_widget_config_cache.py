"""
Redis Widget Configuration Cache (DB 4)
Dedicated Redis database for caching widget display configuration.
Uses same DB as agent cache for co-location of widget state.

Env var: AGENT_CACHE_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/4
"""
import redis.asyncio as redis
import os
from typing import Optional

from shared.otel_logger import get_otel_logger

logger = get_otel_logger(__name__, "shared")

# Global Redis client for widget config cache (database 4)
_widget_config_cache_client: Optional[redis.Redis] = None

CACHE_KEY_PREFIX = "widget:config:"
DISPLAY_CHATBOT_KEY = f"{CACHE_KEY_PREFIX}display_chatbot"
DEFAULT_TTL = 86400  # 24 hours


async def init_widget_config_cache_redis() -> redis.Redis:
    """
    Initialize async Redis client for widget config cache on database 4.

    Requires AGENT_CACHE_REDIS_URL environment variable.
    Format: redis://default:<password>@redis.railway.internal:6379/4

    Returns:
        Async Redis client connected to database 4
    """
    global _widget_config_cache_client

    if _widget_config_cache_client is not None:
        return _widget_config_cache_client

    redis_url = os.getenv('AGENT_CACHE_REDIS_URL')

    if not redis_url:
        # Fallback: derive from PUBSUB_REDIS_URL by changing DB number
        pubsub_url = os.getenv('PUBSUB_REDIS_URL', '')
        if pubsub_url:
            # Replace /3 (or any trailing /N) with /4
            if '/' in pubsub_url.rsplit(':', 1)[-1]:
                redis_url = pubsub_url.rsplit('/', 1)[0] + '/4'
            else:
                redis_url = pubsub_url + '/4'
            logger.info("Derived AGENT_CACHE_REDIS_URL from PUBSUB_REDIS_URL (DB 4)")
        else:
            raise RuntimeError(
                "AGENT_CACHE_REDIS_URL environment variable not set. "
                "Format: redis://default:<password>@redis.railway.internal:6379/4"
            )

    try:
        logger.info("Initializing Redis widget config cache client (database 4)...")

        _widget_config_cache_client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            health_check_interval=30
        )

        await _widget_config_cache_client.ping()
        logger.info("Redis widget config cache client initialized (db=4)")

        return _widget_config_cache_client

    except redis.ConnectionError as e:
        logger.error(f"Failed to connect to Redis widget config cache: {e}")
        raise RuntimeError(f"Redis widget config cache connection failed: {e}")


async def get_widget_config_cache_redis() -> redis.Redis:
    """Get async Redis widget config cache client, initializing if needed."""
    if _widget_config_cache_client is None:
        return await init_widget_config_cache_redis()
    return _widget_config_cache_client


async def get_display_chatbot() -> Optional[bool]:
    """
    Get the display_chatbot configuration from Redis cache.

    Returns:
        True if chat should be displayed, False if disabled, None on cache miss/error
    """
    try:
        client = await get_widget_config_cache_redis()
        value = await client.get(DISPLAY_CHATBOT_KEY)
        if value is not None:
            bool_value = value.lower() == 'true'
            logger.debug(f"✅ Cache HIT: display_chatbot={bool_value}")
            return bool_value
        else:
            logger.debug(f"❌ Cache MISS: display_chatbot (no value)")
            return None
    except Exception as e:
        logger.warning(f"⚠️ Cache GET failed for display_chatbot: {e}")
        return None


async def set_display_chatbot(enabled: bool, ttl: int = DEFAULT_TTL) -> bool:
    """
    Cache the display_chatbot configuration.

    Args:
        enabled: Whether chat should be displayed (True/False)
        ttl: Cache TTL in seconds (default 24 hours)

    Returns:
        True if cached successfully, False on error
    """
    try:
        client = await get_widget_config_cache_redis()
        value = "true" if enabled else "false"
        await client.set(DISPLAY_CHATBOT_KEY, value, ex=ttl)
        logger.info(f"✅ Cache SET: display_chatbot={value} (TTL: {ttl}s)")
        return True
    except Exception as e:
        logger.warning(f"⚠️ Cache SET failed for display_chatbot: {e}")
        return False


async def invalidate_display_chatbot() -> bool:
    """
    Remove the display_chatbot configuration from Redis cache.

    Returns:
        True if invalidated successfully, False on error
    """
    try:
        client = await get_widget_config_cache_redis()
        await client.delete(DISPLAY_CHATBOT_KEY)
        logger.info(f"🗑️ Cache INVALIDATED: display_chatbot")
        return True
    except Exception as e:
        logger.warning(f"⚠️ Cache INVALIDATE failed for display_chatbot: {e}")
        return False
