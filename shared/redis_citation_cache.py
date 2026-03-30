"""
Redis Citation Cache (DB 4)
Caches display_name/storage_document_name → original_url mappings for citation lookups.
Uses same DB as agent cache (DB 4) for co-location of lookup state.

Cache strategy:
- Key format: citation:url:{title} → original_url
- TTL: 24 hours (refreshed on access)
- Populated on cache miss (from DB) and on website scrape completion
- Invalidated when websites are deleted
"""
import redis.asyncio as redis
import json
from typing import Dict, List, Optional

from shared.otel_logger import get_otel_logger
from shared.redis_factory import create_async_redis_client

logger = get_otel_logger(__name__, "shared")

CACHE_KEY_PREFIX = "citation:url:"
DEFAULT_TTL = 86400  # 24 hours


async def _get_redis_client() -> redis.Redis:
    """Get or initialize async Redis client for citation cache (DB 4)."""
    return await create_async_redis_client(
        primary_env_var="AGENT_CACHE_REDIS_URL",
        fallback_env_var="PUBSUB_REDIS_URL",
        fallback_db_suffix="/4",
    )


async def get_cached_urls(titles: List[str]) -> Dict[str, Optional[str]]:
    """
    Batch lookup cached title → URL mappings.

    Returns:
        Dict where key=title, value=url (or None if not cached).
        Only titles found in cache are included.
    """
    if not titles:
        return {}

    try:
        client = await _get_redis_client()
        keys = [f"{CACHE_KEY_PREFIX}{title}" for title in titles]
        values = await client.mget(keys)

        result = {}
        for title, value in zip(titles, values):
            if value is not None:
                result[title] = value
                logger.debug(f"📎 [CITATION_CACHE] HIT: {title} → {value}")

        if result:
            logger.info(f"📎 [CITATION_CACHE] {len(result)}/{len(titles)} cache hits")
        return result

    except Exception as e:
        logger.warning(f"⚠️ [CITATION_CACHE] GET failed: {e}")
        return {}


async def cache_url_mappings(url_map: Dict[str, str], ttl: int = DEFAULT_TTL) -> int:
    """
    Cache multiple title → URL mappings.

    Args:
        url_map: Dict of {title: original_url}
        ttl: Cache TTL in seconds (default 24 hours)

    Returns:
        Number of entries cached successfully
    """
    if not url_map:
        return 0

    try:
        client = await _get_redis_client()
        pipe = client.pipeline()
        for title, url in url_map.items():
            pipe.set(f"{CACHE_KEY_PREFIX}{title}", url, ex=ttl)
        await pipe.execute()
        logger.info(f"📎 [CITATION_CACHE] Cached {len(url_map)} URL mappings (TTL: {ttl}s)")
        return len(url_map)

    except Exception as e:
        logger.warning(f"⚠️ [CITATION_CACHE] SET failed: {e}")
        return 0


async def cache_single_url(title: str, url: str, ttl: int = DEFAULT_TTL) -> bool:
    """Cache a single title → URL mapping. Called when a new website page is scraped."""
    try:
        client = await _get_redis_client()
        await client.set(f"{CACHE_KEY_PREFIX}{title}", url, ex=ttl)
        logger.info(f"📎 [CITATION_CACHE] Cached: {title} → {url}")
        return True
    except Exception as e:
        logger.warning(f"⚠️ [CITATION_CACHE] Single SET failed: {e}")
        return False


async def invalidate_urls(titles: List[str]) -> int:
    """Remove cached URL mappings (e.g., when websites are deleted)."""
    if not titles:
        return 0

    try:
        client = await _get_redis_client()
        keys = [f"{CACHE_KEY_PREFIX}{title}" for title in titles]
        deleted = await client.delete(*keys)
        logger.info(f"🗑️ [CITATION_CACHE] Invalidated {deleted} entries")
        return deleted
    except Exception as e:
        logger.warning(f"⚠️ [CITATION_CACHE] INVALIDATE failed: {e}")
        return 0
