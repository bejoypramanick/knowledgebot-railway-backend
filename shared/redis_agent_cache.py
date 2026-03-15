"""
Redis Agent Assignment Cache (DB 4)
Dedicated Redis database for caching agent-to-session assignments.
Separates agent cache concerns from Pub/Sub (DB 3).

Env var: AGENT_CACHE_REDIS_URL=redis://default:<password>@redis.railway.internal:6379/4
"""
import redis.asyncio as redis
import os
from typing import Optional

from shared.otel_logger import get_otel_logger

logger = get_otel_logger(__name__, "shared")

# Global Redis client for agent cache (database 4)
_agent_cache_client: Optional[redis.Redis] = None

CACHE_KEY_PREFIX = "session:assigned_agent:"
USER_EMAIL_PREFIX = "user:email:"      # email → numeric ID
USER_ID_PREFIX = "user:id:"            # numeric ID → email
ADMIN_IDS_KEY = "cache:admin_ids"      # cached list of admin IDs
DEFAULT_TTL = 3600  # 1 hour
USER_CACHE_TTL = 600  # 10 minutes for user lookups
ADMIN_CACHE_TTL = 300  # 5 minutes for admin list


async def init_agent_cache_redis() -> redis.Redis:
    """
    Initialize async Redis client for agent assignment cache on database 4.

    Requires AGENT_CACHE_REDIS_URL environment variable.
    Format: redis://default:<password>@redis.railway.internal:6379/4

    Returns:
        Async Redis client connected to database 4
    """
    global _agent_cache_client

    if _agent_cache_client is not None:
        return _agent_cache_client

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
        logger.info("Initializing Redis agent cache client (database 4)...")

        _agent_cache_client = redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            health_check_interval=30
        )

        await _agent_cache_client.ping()
        logger.info("Redis agent cache client initialized (db=4)")

        return _agent_cache_client

    except redis.ConnectionError as e:
        logger.error(f"Failed to connect to Redis agent cache: {e}")
        raise RuntimeError(f"Redis agent cache connection failed: {e}")


async def get_agent_cache_redis() -> redis.Redis:
    """Get async Redis agent cache client, initializing if needed."""
    if _agent_cache_client is None:
        return await init_agent_cache_redis()
    return _agent_cache_client


async def get_assigned_agent(session_uuid: str) -> Optional[str]:
    """
    Get the assigned agent ID/email for a session from Redis cache.

    Args:
        session_uuid: Session UUID

    Returns:
        Cached agent value (ID or email) or None if not cached
    """
    try:
        client = await get_agent_cache_redis()
        cache_key = f"{CACHE_KEY_PREFIX}{session_uuid}"
        value = await client.get(cache_key)
        if value:
            logger.debug(f"Agent cache HIT: {session_uuid} -> {value}")
        return value
    except Exception as e:
        logger.warning(f"Agent cache GET failed for {session_uuid}: {e}")
        return None


async def set_assigned_agent(session_uuid: str, agent_value, ttl: int = DEFAULT_TTL) -> bool:
    """
    Cache the assigned agent for a session.

    Args:
        session_uuid: Session UUID
        agent_value: Agent ID (int) or email (str) to cache
        ttl: Cache TTL in seconds (default 1 hour)

    Returns:
        True if cached successfully
    """
    try:
        client = await get_agent_cache_redis()
        cache_key = f"{CACHE_KEY_PREFIX}{session_uuid}"
        await client.set(cache_key, agent_value, ex=ttl)
        logger.debug(f"Agent cache SET: {session_uuid} -> {agent_value} (TTL: {ttl}s)")
        return True
    except Exception as e:
        logger.warning(f"Agent cache SET failed for {session_uuid}: {e}")
        return False


async def clear_assigned_agent(session_uuid: str) -> bool:
    """
    Remove the agent assignment cache for a session.

    Args:
        session_uuid: Session UUID

    Returns:
        True if removed successfully
    """
    try:
        client = await get_agent_cache_redis()
        cache_key = f"{CACHE_KEY_PREFIX}{session_uuid}"
        await client.delete(cache_key)
        logger.debug(f"Agent cache DEL: {session_uuid}")
        return True
    except Exception as e:
        logger.warning(f"Agent cache DEL failed for {session_uuid}: {e}")
        return False


# --- User identity cache (email ↔ ID) ---

async def get_cached_user_id(email: str) -> Optional[int]:
    """Get cached numeric user ID from email."""
    try:
        client = await get_agent_cache_redis()
        value = await client.get(f"{USER_EMAIL_PREFIX}{email}")
        return int(value) if value else None
    except Exception as e:
        logger.warning(f"User ID cache GET failed for {email}: {e}")
        return None


async def set_cached_user_id(email: str, user_id: int) -> None:
    """Cache email → numeric ID and ID → email bidirectionally."""
    try:
        client = await get_agent_cache_redis()
        await client.set(f"{USER_EMAIL_PREFIX}{email}", str(user_id), ex=USER_CACHE_TTL)
        await client.set(f"{USER_ID_PREFIX}{user_id}", email, ex=USER_CACHE_TTL)
    except Exception as e:
        logger.warning(f"User ID cache SET failed for {email}: {e}")


async def get_cached_user_email(user_id: int) -> Optional[str]:
    """Get cached email from numeric user ID."""
    try:
        client = await get_agent_cache_redis()
        return await client.get(f"{USER_ID_PREFIX}{user_id}")
    except Exception as e:
        logger.warning(f"User email cache GET failed for {user_id}: {e}")
        return None


# --- Admin IDs cache ---

async def get_cached_admin_ids() -> Optional[list]:
    """Get cached list of admin IDs. Returns None on miss."""
    try:
        client = await get_agent_cache_redis()
        value = await client.get(ADMIN_IDS_KEY)
        if value:
            import json
            return json.loads(value)
        return None
    except Exception as e:
        logger.warning(f"Admin IDs cache GET failed: {e}")
        return None


async def set_cached_admin_ids(admin_ids: list) -> None:
    """Cache the list of admin IDs."""
    try:
        import json
        client = await get_agent_cache_redis()
        await client.set(ADMIN_IDS_KEY, json.dumps(admin_ids), ex=ADMIN_CACHE_TTL)
    except Exception as e:
        logger.warning(f"Admin IDs cache SET failed: {e}")
