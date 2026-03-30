"""
Redis Connection Factory

Centralised builder for Redis clients across all services.
Eliminates ~200 LOC of duplicated connection setup.

Supports:
  - Async (redis.asyncio) clients for async services
  - Sync (redis) clients for Celery workers
  - Environment variable fallbacks (primary → PUBSUB_REDIS_URL with DB suffix)
  - Standard connection parameters (timeout, keepalive, health check)
  - Per-database client caching
"""
import os
import redis.asyncio as aioredis
import redis as sync_redis
from typing import Optional
from shared.otel_logger import get_otel_logger

logger = get_otel_logger(__name__, "shared")

# Global cache for async clients (keyed by env var)
_async_redis_clients: dict[str, Optional[aioredis.Redis]] = {}

# Global cache for sync clients (keyed by env var)
_sync_redis_clients: dict[str, Optional[sync_redis.Redis]] = {}


async def create_async_redis_client(
    primary_env_var: str,
    fallback_env_var: str = "PUBSUB_REDIS_URL",
    fallback_db_suffix: str = "",
    cache: bool = True,
) -> aioredis.Redis:
    """
    Create or get cached async Redis client.

    Args:
        primary_env_var: Primary environment variable (e.g., 'CHAT_STORE_REDIS_URL')
        fallback_env_var: Fallback env var if primary not set (e.g., 'PUBSUB_REDIS_URL')
        fallback_db_suffix: Append to fallback URL (e.g., '/6' for DB 6)
        cache: If True, reuse cached client for this primary_env_var

    Returns:
        Async Redis client with standard config

    Raises:
        RuntimeError if no valid Redis URL found
    """
    # Return cached if available
    if cache and primary_env_var in _async_redis_clients:
        if _async_redis_clients[primary_env_var] is not None:
            return _async_redis_clients[primary_env_var]

    redis_url = os.getenv(primary_env_var)

    if not redis_url:
        fallback_url = os.getenv(fallback_env_var, "")
        if fallback_url:
            # Parse fallback URL and append DB suffix
            if fallback_db_suffix:
                if "/" in fallback_url.rsplit(":", 1)[-1]:
                    # URL has a DB number, replace it
                    redis_url = fallback_url.rsplit("/", 1)[0] + fallback_db_suffix
                else:
                    # No DB number, append
                    redis_url = fallback_url.rstrip("/") + fallback_db_suffix
                logger.info(
                    f"Derived {primary_env_var} from {fallback_env_var} "
                    f"(DB={fallback_db_suffix.lstrip('/')})"
                )
            else:
                redis_url = fallback_url
        else:
            raise RuntimeError(
                f"Redis URL not configured. Set {primary_env_var} or {fallback_env_var}"
            )

    try:
        logger.info(f"Initializing async Redis client ({primary_env_var})...")

        client = aioredis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
            socket_keepalive=True,
            health_check_interval=30,
        )

        # Test connection
        await client.ping()
        logger.info(f"✅ Async Redis client initialized ({primary_env_var})")

        if cache:
            _async_redis_clients[primary_env_var] = client

        return client

    except aioredis.ConnectionError as e:
        logger.error(f"Failed to connect to Redis ({primary_env_var}): {e}")
        raise RuntimeError(f"Redis connection failed ({primary_env_var}): {e}")


def create_sync_redis_client(
    primary_env_var: str,
    fallback_env_var: str = "",
    fallback_db_suffix: str = "",
    cache: bool = True,
) -> sync_redis.Redis:
    """
    Create or get cached sync Redis client (for Celery, message queues).

    Args:
        primary_env_var: Primary environment variable
        fallback_env_var: Fallback env var if primary not set
        fallback_db_suffix: Append to fallback URL (e.g., '/0')
        cache: If True, reuse cached client for this primary_env_var

    Returns:
        Sync Redis client with standard config

    Raises:
        RuntimeError if no valid Redis URL found
    """
    # Return cached if available
    if cache and primary_env_var in _sync_redis_clients:
        if _sync_redis_clients[primary_env_var] is not None:
            return _sync_redis_clients[primary_env_var]

    redis_url = os.getenv(primary_env_var)

    if not redis_url:
        if fallback_env_var:
            fallback_url = os.getenv(fallback_env_var, "")
            if fallback_url:
                if fallback_db_suffix:
                    if "/" in fallback_url.rsplit(":", 1)[-1]:
                        redis_url = fallback_url.rsplit("/", 1)[0] + fallback_db_suffix
                    else:
                        redis_url = fallback_url.rstrip("/") + fallback_db_suffix
                    logger.info(
                        f"Derived {primary_env_var} from {fallback_env_var} "
                        f"(DB={fallback_db_suffix.lstrip('/')})"
                    )
                else:
                    redis_url = fallback_url

        if not redis_url:
            raise RuntimeError(
                f"Redis URL not configured. Set {primary_env_var}"
                + (f" or {fallback_env_var}" if fallback_env_var else "")
            )

    try:
        logger.info(f"Initializing sync Redis client ({primary_env_var})...")

        client = sync_redis.from_url(
            redis_url,
            decode_responses=True,
            socket_connect_timeout=5,
        )

        # Test connection
        client.ping()
        logger.info(f"✅ Sync Redis client initialized ({primary_env_var})")

        if cache:
            _sync_redis_clients[primary_env_var] = client

        return client

    except sync_redis.ConnectionError as e:
        logger.error(f"Failed to connect to Redis ({primary_env_var}): {e}")
        raise RuntimeError(f"Redis connection failed ({primary_env_var}): {e}")
