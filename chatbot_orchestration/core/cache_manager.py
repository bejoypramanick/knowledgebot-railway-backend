"""
GeminiCacheManager - Manages Gemini explicit context caching lifecycle.

Caches the system prompt + tool declarations so they don't need to be sent
with every request. Gemini gives a 90% discount on cached input tokens.

The cache is GLOBAL (shared across all sessions) because the system prompt
and tools are identical for every customer. Cost control:
- Cache is created when the first session starts
- Cache is DELETED from Google when the last session closes
- Short TTL (10 min default) as safety net for idle hours

Cache includes:
- System instruction (the full system prompt)
- Tool declarations (function signatures)

When active, CachedGoogleModel strips these from the API request to avoid
the 400 error from Gemini (can't send cached_content AND tools/system_instruction).
"""

import asyncio
import hashlib
import json
import os
import time
from typing import Callable, List, Optional

import redis.asyncio as redis
from shared.otel_logger import get_otel_logger

logger = get_otel_logger(__name__, "chatbot-orchestration")

# Default cache TTL: 10 minutes (safety net — cache is explicitly deleted on last session close)
DEFAULT_CACHE_TTL_SECONDS = 600

REDIS_CACHE_METADATA_KEY = "gemini:explicit_cache:metadata"
REDIS_CACHE_SESSIONS_KEY = "gemini:explicit_cache:active_sessions"


class GeminiCacheManager:
    """Manages Gemini cached content lifecycle with hash-based invalidation."""

    def __init__(self):
        self._cache_name: Optional[str] = None
        self._cache_hash: Optional[str] = None
        self._cache_created_at: float = 0
        self._cache_ttl: int = int(os.getenv("GEMINI_CACHE_TTL_SECONDS", str(DEFAULT_CACHE_TTL_SECONDS)))
        self._lock = asyncio.Lock()
        # Store the system prompt and tools for reuse in fallback caches
        self._cached_system_prompt: Optional[str] = None
        self._cached_tool_functions: Optional[List[Callable]] = None
        self._redis_client: Optional[redis.Redis] = None

    async def _get_redis_client(self) -> redis.Redis:
        if self._redis_client is not None:
            return self._redis_client

        redis_url = os.getenv("AGENT_CACHE_REDIS_URL") or os.getenv("CHAT_STORE_REDIS_URL")
        if not redis_url:
            raise RuntimeError("Redis URL not configured for Gemini explicit cache registry")

        self._redis_client = redis.from_url(redis_url, decode_responses=True)
        return self._redis_client

    async def _load_metadata(self) -> Optional[dict]:
        client = await self._get_redis_client()
        raw = await client.get(REDIS_CACHE_METADATA_KEY)
        if not raw:
            return None
        try:
            return json.loads(raw)
        except Exception:
            logger.warning("Failed to decode Redis Gemini cache metadata; clearing it")
            await client.delete(REDIS_CACHE_METADATA_KEY)
            return None

    async def _store_metadata(self, cache_name: str, content_hash: str, model_name: str) -> None:
        client = await self._get_redis_client()
        payload = {
            "cache_name": cache_name,
            "content_hash": content_hash,
            "model_name": model_name,
            "created_at": time.time(),
        }
        await client.set(REDIS_CACHE_METADATA_KEY, json.dumps(payload))

    async def register_session(self, session_id: str) -> None:
        client = await self._get_redis_client()
        await client.sadd(REDIS_CACHE_SESSIONS_KEY, session_id)

    async def unregister_session(self, session_id: str) -> int:
        client = await self._get_redis_client()
        await client.srem(REDIS_CACHE_SESSIONS_KEY, session_id)
        return int(await client.scard(REDIS_CACHE_SESSIONS_KEY))

    async def clear_session_registry(self) -> None:
        client = await self._get_redis_client()
        await client.delete(REDIS_CACHE_SESSIONS_KEY)

    async def _delete_remote_cache_by_name(self, cache_name: str) -> None:
        if not cache_name:
            return
        try:
            from ..core.ai import get_genai_client

            client = get_genai_client()
            if not client:
                logger.warning("GenAI client not available, cannot delete cache")
                return

            await client.aio.caches.delete(name=cache_name)
            logger.info(f"Deleted Gemini cache from Google: {cache_name} (billing stopped)")
        except Exception as e:
            logger.warning(f"Could not delete Gemini cache {cache_name}: {e}")

    def _compute_hash(self, system_prompt: str, tool_functions: List[Callable]) -> str:
        """Compute hash of system prompt + tool names to detect changes."""
        tool_names = sorted(f.__name__ for f in tool_functions)
        content = f"{system_prompt}|{'|'.join(tool_names)}"
        return hashlib.sha256(content.encode()).hexdigest()[:16]

    @property
    def cache_name(self) -> Optional[str]:
        """Returns active cache name, or None if expired/not set."""
        if not self._cache_name:
            return None
        elapsed = time.time() - self._cache_created_at
        if elapsed >= self._cache_ttl:
            logger.info(f"Gemini cache expired locally (elapsed: {elapsed:.0f}s, TTL: {self._cache_ttl}s)")
            self._cache_name = None
            self._cache_hash = None
            return None
        return self._cache_name

    async def ensure_cache(
        self,
        system_prompt: str,
        tool_functions: List[Callable],
        model_name: str,
    ) -> Optional[str]:
        """Create or reuse Gemini cached content.

        Args:
            system_prompt: The full system prompt text
            tool_functions: List of tool functions (for declarations)
            model_name: The Gemini model name (e.g. "gemini-2.5-flash")

        Returns:
            Cache name (e.g. "cachedContents/abc123") or None on failure
        """
        async with self._lock:
            content_hash = self._compute_hash(system_prompt, tool_functions)
            metadata = await self._load_metadata()
            if metadata:
                cached_name = metadata.get("cache_name")
                cached_hash = metadata.get("content_hash")
                cached_model = metadata.get("model_name")
                if cached_name and cached_hash == content_hash and cached_model == model_name:
                    self._cache_name = cached_name
                    self._cache_hash = cached_hash
                    self._cache_created_at = float(metadata.get("created_at") or time.time())
                    self._cached_system_prompt = system_prompt
                    self._cached_tool_functions = tool_functions
                    logger.info(f"Reusing Redis-registered Gemini cache: {cached_name} (hash: {content_hash})")
                    return cached_name

            # Need to create new cache
            try:
                from ..core.ai import get_genai_client
                from ..tools.converters import convert_tools_to_gemini_format

                client = get_genai_client()
                if not client:
                    logger.warning("GenAI client not available, skipping cache creation")
                    return None

                # Convert tool functions to Gemini format
                gemini_tools = convert_tools_to_gemini_format(tool_functions)
                logger.info(f"Converted {len(tool_functions)} tool functions to {len(gemini_tools)} Gemini tools for caching")
                
                if len(tool_functions) > 0 and len(gemini_tools) == 0:
                    logger.error("🚨 CRITICAL: All tool conversions failed! Cache will be created without tools!")
                    logger.error("🚨 This will cause the agent to not have access to search_knowledge_base!")
                
                if gemini_tools:
                    for i, tool in enumerate(gemini_tools):
                        if hasattr(tool, 'function_declarations'):
                            tool_names = [f.name for f in tool.function_declarations]
                            logger.info(f"   Gemini Tool {i+1}: {tool_names}")
                        else:
                            logger.warning(f"   Gemini Tool {i+1}: No function_declarations found")

                # Create cached content
                from google.genai import types

                cache_config = types.CreateCachedContentConfig(
                    system_instruction=system_prompt,
                    tools=gemini_tools if gemini_tools else None,
                    tool_config=types.ToolConfig(
                        function_calling_config=types.FunctionCallingConfig(
                            mode=types.FunctionCallingConfigMode.AUTO,
                        )
                    ) if gemini_tools else None,
                    ttl=f"{self._cache_ttl}s",
                    display_name=f"knowledgebot-system-{content_hash}",
                )

                logger.info(f"Creating Gemini cache (model: {model_name}, TTL: {self._cache_ttl}s, hash: {content_hash})")
                logger.info(f"Cache config includes:")
                logger.info(f"  - System instruction: {len(system_prompt)} chars")
                logger.info(f"  - Tools: {len(gemini_tools) if gemini_tools else 0} tool(s)")
                logger.info(f"  - Tool calling mode: {'AUTO' if gemini_tools else 'none'}")
                if gemini_tools:
                    for tool in gemini_tools:
                        if hasattr(tool, 'function_declarations'):
                            logger.info(f"    - Tool functions: {[f.name for f in tool.function_declarations]}")
                
                cached_content = await client.aio.caches.create(
                    model=model_name,
                    config=cache_config,
                )

                old_cache_name = metadata.get("cache_name") if metadata else None
                if old_cache_name and old_cache_name != cached_content.name:
                    logger.info(f"Deleting superseded Gemini cache before switching active cache: {old_cache_name}")
                    await self._delete_remote_cache_by_name(old_cache_name)

                self._cache_name = cached_content.name
                self._cache_hash = content_hash
                self._cache_created_at = time.time()
                # Store the system prompt and tools for reuse
                self._cached_system_prompt = system_prompt
                self._cached_tool_functions = tool_functions
                await self._store_metadata(self._cache_name, content_hash, model_name)

                logger.info(f"Created Gemini cache: {self._cache_name}")
                if cached_content.usage_metadata:
                    logger.info(f"Cached tokens: {cached_content.usage_metadata.total_token_count}")
                
                return self._cache_name

            except Exception as e:
                error_str = str(e)
                if "too small" in error_str.lower() or "min_total_token_count" in error_str:
                    logger.info(f"Gemini cache skipped: content below minimum token threshold ({error_str}). Agent works fine without cache.")
                else:
                    logger.error(f"Failed to create Gemini cache: {e}", exc_info=True)
                logger.warning("Falling back to non-cached mode (agent works without cache)")
                return None

    async def delete_cache(self):
        """Delete the cached content from Google to stop billing.

        Called when the last active session closes. Safe to call multiple times.
        """
        async with self._lock:
            metadata = await self._load_metadata()
            cache_name = (metadata or {}).get("cache_name") or self._cache_name

            self._cache_name = None
            self._cache_hash = None
            self._cache_created_at = 0
            self._cached_system_prompt = None
            self._cached_tool_functions = None

            if cache_name:
                await self._delete_remote_cache_by_name(cache_name)

            client = await self._get_redis_client()
            await client.delete(REDIS_CACHE_METADATA_KEY)

    def invalidate(self, keep_cached_content: bool = False):
        """Clear local cache reference (does NOT delete from Google).

        Args:
            keep_cached_content: If True, preserve the last-known system prompt and
                tool functions so we can rebuild a broken cache deterministically.

        Use delete_cache() to also stop Google billing.
        """
        if self._cache_name:
            logger.info(f"Invalidating local Gemini cache reference: {self._cache_name}")
        self._cache_name = None
        self._cache_hash = None
        self._cache_created_at = 0
        if not keep_cached_content:
            self._cached_system_prompt = None
            self._cached_tool_functions = None

    def get_cached_content(self) -> tuple[Optional[str], Optional[List[Callable]]]:
        """Get the cached system prompt and tool functions for reuse in fallback caches.
        
        Returns:
            Tuple of (system_prompt, tool_functions) or (None, None) if not available
        """
        return self._cached_system_prompt, self._cached_tool_functions


# Global singleton
gemini_cache_manager = GeminiCacheManager()
