"""
Tenant-aware Redis auth/profile cache (DB 8).

This cache is shared by the API gateway and configuration service to reduce
login/profile latency without weakening tenant isolation. Every key is scoped
either by verified user identity, tenant selection, or both.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Optional

import redis.asyncio as redis

from shared.otel_logger import get_otel_logger
from shared.redis_factory import create_async_redis_client
from shared.tenant_context import DEFAULT_TENANT_ID, get_current_tenant_id, get_current_tenant_slug

logger = get_otel_logger(__name__, "shared")

TENANT_AUTH_CACHE_REDIS_DB = 8

USER_MEMBERSHIPS_KEY_PREFIX = "tenant_auth:user_memberships:"
USER_PROFILE_KEY_PREFIX = "tenant_auth:user_profile:"
ROLE_DIRECTORY_KEY_PREFIX = "tenant_auth:role_directory:"

USER_MEMBERSHIPS_TTL = 300
USER_PROFILE_TTL = 300
ROLE_DIRECTORY_TTL = 120


def _normalize_email(email: str) -> str:
    return (email or "").strip().lower()


def _selected_tenant_scope(
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
) -> str:
    if tenant_id:
        return f"tenant_id:{tenant_id}"
    if tenant_slug:
        return f"tenant_slug:{tenant_slug}"
    return "default"


def _active_tenant_scope(
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
) -> str:
    return (
        tenant_id
        or get_current_tenant_id()
        or tenant_slug
        or get_current_tenant_slug()
        or DEFAULT_TENANT_ID
    )


def _user_memberships_key(email: str) -> str:
    return f"{USER_MEMBERSHIPS_KEY_PREFIX}{_normalize_email(email)}"


def _user_profile_key(
    email: str,
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
) -> str:
    selected_scope = _selected_tenant_scope(tenant_id=tenant_id, tenant_slug=tenant_slug)
    return f"{USER_PROFILE_KEY_PREFIX}{_normalize_email(email)}:{selected_scope}"


def _user_profile_pattern(email: str) -> str:
    return f"{USER_PROFILE_KEY_PREFIX}{_normalize_email(email)}:*"


def _role_directory_key(
    role_name: str,
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
) -> str:
    tenant_scope = _active_tenant_scope(tenant_id=tenant_id, tenant_slug=tenant_slug)
    return f"{ROLE_DIRECTORY_KEY_PREFIX}{role_name}:tenant:{tenant_scope}"


async def init_tenant_auth_cache_redis() -> redis.Redis:
    """
    Initialize async Redis client for tenant auth cache on database 8.

    Uses REDIS_URL plus TENANT_AUTH_CACHE_REDIS_DB (default 8).
    """
    return await create_async_redis_client(
        primary_env_var="tenant_auth_cache",
        db_env_var="TENANT_AUTH_CACHE_REDIS_DB",
        default_db=TENANT_AUTH_CACHE_REDIS_DB,
    )


async def get_tenant_auth_cache_redis() -> redis.Redis:
    """Get async Redis tenant auth cache client, initializing if needed."""
    return await init_tenant_auth_cache_redis()


async def _get_json(key: str) -> Optional[Any]:
    try:
        client = await get_tenant_auth_cache_redis()
        value = await client.get(key)
        if value is None:
            logger.debug(f"Auth cache MISS: {key}")
            return None
        logger.debug(f"Auth cache HIT: {key}")
        return json.loads(value)
    except Exception as e:
        logger.warning(f"Auth cache GET failed for {key}: {e}")
        return None


async def _set_json(key: str, payload: Any, ttl: int) -> bool:
    try:
        client = await get_tenant_auth_cache_redis()
        await client.set(key, json.dumps(payload, default=str), ex=ttl)
        logger.debug(f"Auth cache SET: {key} (TTL={ttl}s)")
        return True
    except Exception as e:
        logger.warning(f"Auth cache SET failed for {key}: {e}")
        return False


async def get_cached_user_memberships(email: str) -> Optional[List[Dict[str, Any]]]:
    """Get cached grouped tenant memberships for a user."""
    if not email:
        return None
    cached = await _get_json(_user_memberships_key(email))
    return cached if isinstance(cached, list) else None


async def set_cached_user_memberships(
    email: str,
    memberships: List[Dict[str, Any]],
    ttl: int = USER_MEMBERSHIPS_TTL,
) -> bool:
    """Cache grouped tenant memberships for a user."""
    if not email:
        return False
    return await _set_json(_user_memberships_key(email), memberships, ttl)


async def get_cached_user_profile(
    email: str,
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
) -> Optional[Dict[str, Any]]:
    """Get cached tenant-selected auth/profile context for a user."""
    if not email:
        return None
    cached = await _get_json(_user_profile_key(email, tenant_id=tenant_id, tenant_slug=tenant_slug))
    return cached if isinstance(cached, dict) else None


async def set_cached_user_profile(
    email: str,
    profile: Dict[str, Any],
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
    ttl: int = USER_PROFILE_TTL,
) -> bool:
    """Cache tenant-selected auth/profile context for a user."""
    if not email:
        return False
    return await _set_json(
        _user_profile_key(email, tenant_id=tenant_id, tenant_slug=tenant_slug),
        profile,
        ttl,
    )


async def invalidate_user_auth_cache(email: str) -> int:
    """
    Invalidate all cached memberships/profile entries for a user.

    Returns:
        Number of deleted keys.
    """
    if not email:
        return 0

    deleted = 0
    try:
        client = await get_tenant_auth_cache_redis()
        memberships_key = _user_memberships_key(email)
        deleted += await client.delete(memberships_key)

        async for key in client.scan_iter(match=_user_profile_pattern(email)):
            deleted += await client.delete(key)

        if deleted:
            logger.info(f"Invalidated {deleted} tenant auth cache key(s) for {_normalize_email(email)}")
        return deleted
    except Exception as e:
        logger.warning(f"User auth cache invalidation failed for {email}: {e}")
        return 0


async def get_cached_role_directory(
    role_name: str,
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
) -> Optional[List[Dict[str, Any]]]:
    """Get a cached tenant-scoped admin/human-agent directory."""
    cached = await _get_json(_role_directory_key(role_name, tenant_id=tenant_id, tenant_slug=tenant_slug))
    return cached if isinstance(cached, list) else None


async def set_cached_role_directory(
    role_name: str,
    entries: List[Dict[str, Any]],
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
    ttl: int = ROLE_DIRECTORY_TTL,
) -> bool:
    """Cache a tenant-scoped admin/human-agent directory."""
    return await _set_json(
        _role_directory_key(role_name, tenant_id=tenant_id, tenant_slug=tenant_slug),
        entries,
        ttl,
    )


async def invalidate_role_directory(
    role_name: str,
    tenant_id: Optional[str] = None,
    tenant_slug: Optional[str] = None,
) -> bool:
    """Invalidate a tenant-scoped admin/human-agent directory cache entry."""
    try:
        client = await get_tenant_auth_cache_redis()
        cache_key = _role_directory_key(role_name, tenant_id=tenant_id, tenant_slug=tenant_slug)
        deleted = await client.delete(cache_key)
        if deleted:
            logger.info(f"Invalidated tenant role directory cache: {cache_key}")
        return bool(deleted)
    except Exception as e:
        logger.warning(f"Role directory cache invalidation failed for {role_name}: {e}")
        return False
