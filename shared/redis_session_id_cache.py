"""
Redis Session UUID -> Numeric ID Cache (DB 5)
Dedicated Redis database for caching session UUID to numeric ID mappings.
Used by API Gateway to avoid repeated database lookups.

Env var: SESSION_ID_CACHE_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/5
"""
import redis.asyncio as redis
import os
from typing import Optional

from shared.otel_logger import get_otel_logger

logger = get_otel_logger(__name__, "shared")

# Global Redis client for session ID cache (database 5)
_session_id_cache_client: Optional[redis.Redis] = None

CACHE_KEY_PREFIX = "session:uuid_to_id:"
DEFAULT_TTL = 3600  # 1 hour


async def init_session_id_cache_redis() -> redis.Redis:
    """
    Initialize async Redis client for session ID cache on database 5.

    Requires SESSION_ID_CACHE_REDIS_URL environment variable.
    Format: redis://default:<password>@redis.railway.internal:6379/5

    Returns:
        Async Redis client connected to database 5
    """
    global _session_id_cache_client

    if _session_id_cache_client is not None:
        return _session_id_cache_client

    redis_url = os.getenv('SESSION_ID_CACHE_REDIS_URL')

    if not redis_url:
        # Fallback: derive from PUBSUB_REDIS_URL by changing DB number
        pubsub_url = os.getenv('PUBSUB_REDIS_URL', '')
        if pubsub_url:
            if '/' in pubsub_url.rsplit(':', 1)[-1]:
                redis_url = pubsub_url.rsplit('/', 1)[0] + '/5'
            else:
                redis_url = pubsub_url + '/5'
            logger.info("Derived SESSION_ID_CACHE_REDIS_URL from PUBSUB_REDIS_URL (DB 5)")
        else:
            raise RuntimeError(
                "SESSION_ID_CACHE_REDIS_URL environment variable not set. "
                "Format: redis://default:<password>@redis.railway.internal:6379/5"
            )

    try:
        logger.info("Initializing Redis session ID cache client (database 5)...")

        _session_id_cache_client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            health_check_interval=30
        )

        await _session_id_cache_client.ping()
        logger.info("Redis session ID cache client initialized (db=5)")

        return _session_id_cache_client

    except redis.ConnectionError as e:
        logger.error(f"Failed to connect to Redis session ID cache: {e}")
        raise RuntimeError(f"Redis session ID cache connection failed: {e}")


async def get_session_id_cache_redis() -> redis.Redis:
    """Get async Redis session ID cache client, initializing if needed."""
    if _session_id_cache_client is None:
        return await init_session_id_cache_redis()
    return _session_id_cache_client


async def get_numeric_id(session_uuid: str) -> Optional[int]:
    """
    Get the numeric database ID for a session UUID from Redis cache.

    Args:
        session_uuid: Session UUID

    Returns:
        Numeric session ID or None if not cached
    """
    try:
        client = await get_session_id_cache_redis()
        cache_key = f"{CACHE_KEY_PREFIX}{session_uuid}"
        cached_id = await client.get(cache_key)
        if cached_id:
            numeric_id = int(cached_id)
            logger.debug(f"Session ID cache HIT: {session_uuid} -> {numeric_id}")
            return numeric_id
        return None
    except Exception as e:
        logger.warning(f"Session ID cache GET failed for {session_uuid}: {e}")
        return None


async def set_numeric_id(session_uuid: str, numeric_id: int, ttl: int = DEFAULT_TTL) -> bool:
    """
    Cache the numeric ID for a session UUID.

    Args:
        session_uuid: Session UUID
        numeric_id: Numeric database ID
        ttl: Cache TTL in seconds (default 1 hour)

    Returns:
        True if cached successfully
    """
    try:
        client = await get_session_id_cache_redis()
        cache_key = f"{CACHE_KEY_PREFIX}{session_uuid}"
        await client.setex(cache_key, ttl, str(numeric_id))
        logger.debug(f"Session ID cache SET: {session_uuid} -> {numeric_id} (TTL: {ttl}s)")
        return True
    except Exception as e:
        logger.warning(f"Session ID cache SET failed for {session_uuid}: {e}")
        return False
