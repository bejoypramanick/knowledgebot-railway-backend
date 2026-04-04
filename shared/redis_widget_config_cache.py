"""
Redis Widget Configuration Cache (DB 4)
Dedicated Redis database for caching widget display configuration.
Uses same DB as agent cache for co-location of widget state.

Env var: AGENT_CACHE_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/4
"""
import redis.asyncio as redis
from typing import Optional

from shared.otel_logger import get_otel_logger
from shared.redis_factory import create_async_redis_client
from shared.tenant_context import DEFAULT_TENANT_ID, get_current_tenant_id, get_current_tenant_slug

logger = get_otel_logger(__name__, "shared")

CACHE_KEY_PREFIX = "widget:config:"
DISPLAY_CHATBOT_KEY = f"{CACHE_KEY_PREFIX}display_chatbot"
DEFAULT_TTL = 86400  # 24 hours


def _display_chatbot_key(tenant_id: Optional[str] = None) -> str:
    scoped_tenant_key = tenant_id or get_current_tenant_id() or get_current_tenant_slug() or DEFAULT_TENANT_ID
    return f"{DISPLAY_CHATBOT_KEY}:tenant:{scoped_tenant_key}"


async def init_widget_config_cache_redis() -> redis.Redis:
    """
    Initialize async Redis client for widget config cache on database 4.

    Requires AGENT_CACHE_REDIS_URL environment variable.
    Format: redis://default:<password>@redis.railway.internal:6379/4

    Returns:
        Async Redis client connected to database 4
    """
    return await create_async_redis_client(
        primary_env_var="AGENT_CACHE_REDIS_URL",
        fallback_env_var="PUBSUB_REDIS_URL",
        fallback_db_suffix="/4",
    )


async def get_widget_config_cache_redis() -> redis.Redis:
    """Get async Redis widget config cache client, initializing if needed."""
    return await init_widget_config_cache_redis()


async def get_display_chatbot(tenant_id: Optional[str] = None) -> Optional[bool]:
    """
    Get the display_chatbot configuration from Redis cache.

    Returns:
        True if chat should be displayed, False if disabled, None on cache miss/error
    """
    try:
        client = await get_widget_config_cache_redis()
        cache_key = _display_chatbot_key(tenant_id)
        value = await client.get(cache_key)
        if value is not None:
            bool_value = value.lower() == 'true'
            logger.debug(f"✅ Cache HIT: {cache_key}={bool_value}")
            return bool_value
        else:
            logger.debug(f"❌ Cache MISS: {cache_key} (no value)")
            return None
    except Exception as e:
        logger.warning(f"⚠️ Cache GET failed for display_chatbot: {e}")
        return None


async def set_display_chatbot(enabled: bool, ttl: int = DEFAULT_TTL, tenant_id: Optional[str] = None) -> bool:
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
        cache_key = _display_chatbot_key(tenant_id)
        value = "true" if enabled else "false"
        await client.set(cache_key, value, ex=ttl)
        logger.info(f"✅ Cache SET: {cache_key}={value} (TTL: {ttl}s)")
        return True
    except Exception as e:
        logger.warning(f"⚠️ Cache SET failed for display_chatbot: {e}")
        return False


async def invalidate_display_chatbot(tenant_id: Optional[str] = None) -> bool:
    """
    Remove the display_chatbot configuration from Redis cache.

    Returns:
        True if invalidated successfully, False on error
    """
    try:
        client = await get_widget_config_cache_redis()
        cache_key = _display_chatbot_key(tenant_id)
        await client.delete(cache_key)
        logger.info(f"🗑️ Cache INVALIDATED: {cache_key}")
        return True
    except Exception as e:
        logger.warning(f"⚠️ Cache INVALIDATE failed for display_chatbot: {e}")
        return False
