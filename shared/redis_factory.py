"""
Redis Connection Factory

Centralised builder for Redis clients across all services.
Eliminates ~200 LOC of duplicated connection setup.

Supports:
  - Async (redis.asyncio) clients for async services
  - Sync (redis) clients for Celery workers
  - One shared REDIS_URL plus purpose-specific DB env vars
  - Standard connection parameters (timeout, keepalive, health check)
  - Per-database client caching
"""
import os
import redis.asyncio as aioredis
import redis as sync_redis
from typing import Optional
from urllib.parse import urlparse, urlunparse
from shared.otel_logger import get_otel_logger

logger = get_otel_logger(__name__, "shared")

# Global cache for async clients (keyed by env var)
_async_redis_clients: dict[str, Optional[aioredis.Redis]] = {}

# Global cache for sync clients (keyed by env var)
_sync_redis_clients: dict[str, Optional[sync_redis.Redis]] = {}


def _build_redis_url_with_db(base_url: str, db: int) -> str:
    parsed = urlparse(base_url)
    if not parsed.scheme or not parsed.netloc:
        raise RuntimeError("Invalid Redis base URL")

    return urlunparse((
        parsed.scheme,
        parsed.netloc,
        f"/{db}",
        parsed.params,
        parsed.query,
        parsed.fragment,
    ))


def resolve_redis_url(
    primary_env_var: str,
    db_env_var: str,
    default_db: int,
    base_env_var: str = "REDIS_URL",
) -> str:
    """
    Resolve a Redis URL from either:
    REDIS_URL plus a purpose-specific DB env var/default DB.
    """
    base_url = os.getenv(base_env_var, "").strip()
    if not base_url:
        raise RuntimeError(
            f"Redis URL not configured. Set {base_env_var}"
        )

    resolved_db = default_db
    db_value = os.getenv(db_env_var, "").strip()
    if db_value:
        try:
            resolved_db = int(db_value)
        except ValueError as exc:
            raise RuntimeError(f"Invalid integer value for {db_env_var}: {db_value}") from exc

    redis_url = _build_redis_url_with_db(base_url, resolved_db)
    logger.info(
        f"Derived {primary_env_var} from {base_env_var} "
        f"(DB={resolved_db} via {db_env_var})"
    )
    return redis_url


async def create_async_redis_client(
    primary_env_var: str,
    db_env_var: str,
    default_db: int,
    base_env_var: str = "REDIS_URL",
    cache: bool = True,
) -> aioredis.Redis:
    """
    Create or get cached async Redis client.

    Args:
        primary_env_var: Logical Redis purpose name used for logging/cache keys
        db_env_var: DB number env var paired with REDIS_URL (e.g., 'CHAT_STORE_REDIS_DB')
        default_db: Default Redis DB if db_env_var is unset
        base_env_var: Base URL env var (default: REDIS_URL)
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

    redis_url = resolve_redis_url(
        primary_env_var=primary_env_var,
        db_env_var=db_env_var,
        default_db=default_db,
        base_env_var=base_env_var,
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
    db_env_var: str,
    default_db: int,
    base_env_var: str = "REDIS_URL",
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

    redis_url = resolve_redis_url(
        primary_env_var=primary_env_var,
        db_env_var=db_env_var,
        default_db=default_db,
        base_env_var=base_env_var,
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
