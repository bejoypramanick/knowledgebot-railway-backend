"""
Redis UI Data Cache (DB 7)
Pre-loads and caches UI screen data (Chat Agent Config, Widget Config,
Performance Metrics, Knowledge Base) so frontend fetches from Redis
instead of PostgreSQL on every page load.

Cache is warmed on server start and invalidated on mutations.

Redis DB layout: DB0=file tasks, DB1=web tasks, DB2=extractor,
DB3=pub/sub+presence, DB4=agent cache, DB5=session UUID cache,
DB6=chat store, DB7=UI cache (this module)
"""
import json
from typing import Optional

import redis.asyncio as redis

from shared.otel_logger import get_otel_logger
from shared.redis_factory import create_async_redis_client
from shared.tenant_context import DEFAULT_TENANT_ID, get_current_tenant_id, get_current_tenant_slug

logger = get_otel_logger(__name__, "shared")

# Global Redis client for UI cache (database 7)
_ui_cache_client: Optional[redis.Redis] = None

UI_CACHE_REDIS_DB = 7

# Cache keys
CHAT_AGENT_CONFIG_KEY = "ui_cache:chat_agent_config"
WIDGET_CONFIG_KEY = "ui_cache:widget_config"
PERFORMANCE_METRICS_KEY = "ui_cache:performance_metrics"
TOKEN_USAGE_KEY_PREFIX = "ui_cache:token_usage:"
KB_FILES_KEY_PREFIX = "ui_cache:kb_files:"

# TTLs
TTL_LONG = 300        # 5 minutes — config screens
TTL_WIDGET = 300      # 5 minutes — widget config
TTL_MEDIUM = 600      # 10 minutes — knowledge base
TTL_SHORT = 300       # 5 minutes — performance/token usage


def _is_already_scoped(key: str) -> bool:
    return ":tenant:" in key


def _is_tenant_scoped_key(key: str) -> bool:
    if key in {CHAT_AGENT_CONFIG_KEY, WIDGET_CONFIG_KEY, PERFORMANCE_METRICS_KEY}:
        return True
    return key.startswith(TOKEN_USAGE_KEY_PREFIX) or key.startswith(KB_FILES_KEY_PREFIX)


def normalize_cache_key(key: str, tenant_id: Optional[str] = None) -> str:
    if not key or _is_already_scoped(key) or not _is_tenant_scoped_key(key):
        return key

    if key.startswith(TOKEN_USAGE_KEY_PREFIX):
        suffix = key[len(TOKEN_USAGE_KEY_PREFIX):]
        return f"{scope_cache_prefix(TOKEN_USAGE_KEY_PREFIX, tenant_id)}{suffix}"

    if key.startswith(KB_FILES_KEY_PREFIX):
        suffix = key[len(KB_FILES_KEY_PREFIX):]
        return f"{scope_cache_prefix(KB_FILES_KEY_PREFIX, tenant_id)}{suffix}"

    return scope_cache_key(key, tenant_id)


async def init_ui_cache_redis() -> redis.Redis:
    """Initialize async Redis client for UI cache on database 7."""
    global _ui_cache_client

    if _ui_cache_client is not None:
        return _ui_cache_client

    try:
        logger.info(f"Initializing Redis UI cache client (database {UI_CACHE_REDIS_DB})...")
        _ui_cache_client = await create_async_redis_client(
            primary_env_var="ui_data_cache",
            db_env_var="UI_DATA_CACHE_REDIS_DB",
            default_db=UI_CACHE_REDIS_DB,
        )
        logger.info(f"✅ Redis UI cache client initialized (db={UI_CACHE_REDIS_DB})")
        return _ui_cache_client

    except redis.ConnectionError as e:
        logger.error(f"❌ Redis UI cache connection failed: {e}")
        raise RuntimeError(f"Redis UI cache connection failed: {e}")


async def get_ui_cache_redis() -> redis.Redis:
    """Get async Redis UI cache client, initializing if needed."""
    if _ui_cache_client is None:
        return await init_ui_cache_redis()
    return _ui_cache_client


async def cache_get(key: str) -> Optional[dict]:
    """Get a cached value. Returns None on miss or error."""
    try:
        key = normalize_cache_key(key)
        client = await get_ui_cache_redis()
        value = await client.get(key)
        if value is not None:
            logger.debug(f"✅ Cache HIT: {key}")
            return json.loads(value)
        logger.debug(f"❌ Cache MISS: {key}")
        return None
    except Exception as e:
        logger.warning(f"⚠️ Cache GET failed for {key}: {e}")
        return None


async def cache_set(key: str, data, ttl: int) -> bool:
    """Cache a value as JSON with TTL. Returns True on success."""
    try:
        key = normalize_cache_key(key)
        client = await get_ui_cache_redis()
        await client.set(key, json.dumps(data, default=str), ex=ttl)
        logger.info(f"✅ Cache SET: {key} (TTL: {ttl}s)")
        return True
    except Exception as e:
        logger.warning(f"⚠️ Cache SET failed for {key}: {e}")
        return False


async def cache_invalidate(key: str) -> bool:
    """Delete a specific cache key. Returns True on success."""
    try:
        key = normalize_cache_key(key)
        client = await get_ui_cache_redis()
        await client.delete(key)
        logger.info(f"🗑️ Cache INVALIDATED: {key}")
        return True
    except Exception as e:
        logger.warning(f"⚠️ Cache INVALIDATE failed for {key}: {e}")
        return False


async def cache_invalidate_pattern(pattern: str) -> int:
    """Delete all keys matching a glob pattern. Returns count deleted."""
    try:
        client = await get_ui_cache_redis()
        count = 0
        async for key in client.scan_iter(match=pattern):
            await client.delete(key)
            count += 1
        if count:
            logger.info(f"🗑️ Cache INVALIDATED {count} keys matching {pattern}")
        return count
    except Exception as e:
        logger.warning(f"⚠️ Cache INVALIDATE pattern failed for {pattern}: {e}")
        return 0


async def close_ui_cache_redis():
    """Close the Redis UI cache client on shutdown."""
    global _ui_cache_client
    if _ui_cache_client is not None:
        await _ui_cache_client.close()
        _ui_cache_client = None
        logger.info("🛑 Redis UI cache client closed")


def scope_cache_key(key: str, tenant_id: Optional[str] = None) -> str:
    scoped_tenant_key = tenant_id or get_current_tenant_id() or get_current_tenant_slug() or DEFAULT_TENANT_ID
    return f"{key}:tenant:{scoped_tenant_key}"


def scope_cache_prefix(prefix: str, tenant_id: Optional[str] = None) -> str:
    scoped_tenant_key = tenant_id or get_current_tenant_id() or get_current_tenant_slug() or DEFAULT_TENANT_ID
    return f"{prefix}tenant:{scoped_tenant_key}:"


async def invalidate_kb_caches(tenant_id: Optional[str] = None) -> int:
    """
    Invalidate knowledge base UI caches for the active tenant only.
    """
    try:
        pattern = f"{scope_cache_prefix(KB_FILES_KEY_PREFIX, tenant_id)}*"
        count = await cache_invalidate_pattern(pattern)
        if count:
            logger.info(f"🧹 Knowledge base UI caches invalidated ({count} keys)")
        return count
    except Exception as e:
        logger.warning(f"⚠️ Failed to invalidate KB caches: {e}")
        return 0


async def invalidate_all_kb_caches() -> int:
    """
    Invalidate all knowledge base UI cache variants.

    Some mutation paths run without tenant context, while the list endpoint
    stores tenant-scoped keys. A broad purge keeps deletes from leaving stale
    active/deleted rows visible until the cache TTL expires.
    """
    patterns = [
        f"{KB_FILES_KEY_PREFIX}*",
        f"*{KB_FILES_KEY_PREFIX}*",
        "*kb_files*",
    ]
    total = 0
    try:
        for pattern in patterns:
            total += await cache_invalidate_pattern(pattern)
        if total:
            logger.info(f"🧹 All knowledge base UI caches invalidated ({total} keys)")
        return total
    except Exception as e:
        logger.warning(f"⚠️ Failed to invalidate all KB caches: {e}")
        return total
