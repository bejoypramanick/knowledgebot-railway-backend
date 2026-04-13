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
from typing import Callable, List, Optional, Union

import redis.asyncio as redis
from pydantic_ai.tools import ToolDefinition
from shared.otel_logger import get_otel_logger
from shared.redis_factory import resolve_redis_url
from shared.usage_tracking import track_model_usage

logger = get_otel_logger(__name__, "chatbot-orchestration")

# Default cache TTL: 1 hour (safety net — cache is explicitly deleted on last session close)
DEFAULT_CACHE_TTL_SECONDS = 3600

REDIS_CACHE_METADATA_KEY = "gemini:explicit_cache:metadata"
REDIS_CACHE_SESSIONS_KEY = "gemini:explicit_cache:active_sessions"
CACHE_PROMPT_VERSION = os.getenv("GEMINI_CACHE_PROMPT_VERSION", "2026-04-11-v2")


def _count_tokens_with_sdk(client, model_name: str, content: str) -> Optional[int]:
    if not content:
        return 0
    try:
        response = client.models.count_tokens(model=model_name, contents=content)
        total_tokens = getattr(response, "total_tokens", None)
        return int(total_tokens) if total_tokens is not None else None
    except Exception as e:
        logger.warning(f"Could not count tokens with Google SDK for model={model_name}: {e}")
        return None


def _serialize_gemini_tools(gemini_tools: list) -> str:
    serialized_tools: list[dict] = []
    for tool in gemini_tools or []:
        function_declarations = []
        declarations = getattr(tool, "function_declarations", None) or []
        for decl in declarations:
            function_declarations.append(
                {
                    "name": getattr(decl, "name", None),
                    "description": getattr(decl, "description", None),
                    "parameters": getattr(decl, "parameters", None).model_dump(exclude_none=True)
                    if getattr(decl, "parameters", None) is not None and hasattr(getattr(decl, "parameters", None), "model_dump")
                    else getattr(decl, "parameters", None),
                }
            )
        serialized_tools.append({"function_declarations": function_declarations})
    return json.dumps(serialized_tools, ensure_ascii=False, sort_keys=True)


class GeminiCacheManager:
    """Manages Gemini cached content lifecycle with Redis as the cache-id registry."""

    def __init__(self):
        self._cache_name: Optional[str] = None
        self._cache_created_at: float = 0
        self._cache_ttl: int = int(os.getenv("GEMINI_CACHE_TTL_SECONDS", str(DEFAULT_CACHE_TTL_SECONDS)))
        self._lock = asyncio.Lock()
        # Store the system prompt and tools for reuse in fallback caches
        self._cached_system_prompt: Optional[str] = None
        self._cached_tool_functions: Optional[List[Union[Callable, ToolDefinition]]] = None
        self._redis_client: Optional[redis.Redis] = None
        self._last_ensure_stats: dict = {
            "create_attempts": 0,
            "create_failures": 0,
            "reused_existing": False,
            "recreated_remote": False,
            "last_error": None,
        }

    def _build_prompt_fingerprint(
        self,
        system_prompt: str,
        model_name: str,
        serialized_tool_schema: str,
    ) -> str:
        payload = "\n".join(
            [
                CACHE_PROMPT_VERSION,
                model_name or "",
                system_prompt or "",
                serialized_tool_schema or "",
            ]
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def get_last_ensure_stats(self) -> dict:
        return dict(self._last_ensure_stats)

    async def _get_redis_client(self) -> redis.Redis:
        if self._redis_client is not None:
            return self._redis_client

        redis_url = resolve_redis_url(
            primary_env_var="gemini_cache_registry",
            db_env_var="AGENT_ASSIGNMENT_CACHE_REDIS_DB",
            default_db=4,
        )

        self._redis_client = redis.from_url(redis_url, decode_responses=True)
        return self._redis_client

    async def _load_metadata(self) -> Optional[dict]:
        client = await self._get_redis_client()
        raw = await client.get(REDIS_CACHE_METADATA_KEY)
        if not raw:
            logger.info("🗃️ [CACHE_REDIS_LOAD] metadata=missing")
            return None
        try:
            decoded = json.loads(raw)
            logger.info(
                "🗃️ [CACHE_REDIS_LOAD] "
                f"cache_name={decoded.get('cache_name')} "
                f"model_name={decoded.get('model_name')} "
                f"has_tools={decoded.get('has_tools')} "
                f"created_at={decoded.get('created_at')}"
            )
            return decoded
        except Exception:
            logger.warning("Failed to decode Redis Gemini cache metadata; clearing it")
            await client.delete(REDIS_CACHE_METADATA_KEY)
            return None

    async def _store_metadata(
        self,
        cache_name: str,
        model_name: str,
        has_tools: bool = False,
        prompt_fingerprint: Optional[str] = None,
    ) -> None:
        client = await self._get_redis_client()
        payload = {
            "cache_name": cache_name,
            "model_name": model_name,
            "has_tools": has_tools,
            "created_at": time.time(),
            "prompt_fingerprint": prompt_fingerprint,
            "prompt_version": CACHE_PROMPT_VERSION,
        }
        await client.set(REDIS_CACHE_METADATA_KEY, json.dumps(payload))
        logger.info(
            "🗃️ [CACHE_REDIS_STORE] "
            f"cache_name={cache_name} "
            f"model_name={model_name} "
            f"has_tools={has_tools} "
            f"created_at={payload['created_at']}"
        )

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

            logger.info(f"🗑️ [CACHE_REMOTE_DELETE] cache_name={cache_name}")
            await client.aio.caches.delete(name=cache_name)
            logger.info(f"Deleted Gemini cache from Google: {cache_name} (billing stopped)")
        except Exception as e:
            logger.warning(f"Could not delete Gemini cache {cache_name}: {e}")

    @property
    def cache_name(self) -> Optional[str]:
        """Returns active cache name, or None if not set.
        
        Note: We no longer check TTL locally. Gemini is the sole source of truth
        for cache expiry. If a request fails with a cache error, the model
        wrapper will trigger a rebuild.
        """
        return self._cache_name

    @property
    def has_tools(self) -> bool:
        """Returns True if the active cache contains tools."""
        if not self.cache_name: # Uses the property to check TTL
            return False
        return getattr(self, "_has_tools", False)

    async def ensure_cache(
        self,
        system_prompt: str,
        tool_functions: List[Union[Callable, ToolDefinition]],
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
            self._last_ensure_stats = {
                "create_attempts": 0,
                "create_failures": 0,
                "reused_existing": False,
                "recreated_remote": False,
                "last_error": None,
            }
            metadata = await self._load_metadata()
            from ..tools.converters import convert_tools_to_gemini_format

            gemini_tools = convert_tools_to_gemini_format(tool_functions)
            serialized_tool_schema = _serialize_gemini_tools(gemini_tools)
            prompt_fingerprint = self._build_prompt_fingerprint(
                system_prompt,
                model_name,
                serialized_tool_schema,
            )

            if metadata:
                cached_name = metadata.get("cache_name")
                cached_fingerprint = metadata.get("prompt_fingerprint")
                if cached_name and cached_fingerprint == prompt_fingerprint:
                    self._cache_name = cached_name
                    self._cache_created_at = float(metadata.get("created_at") or time.time())
                    self._has_tools = bool(metadata.get("has_tools", False))
                    self._cached_system_prompt = system_prompt
                    self._cached_tool_functions = tool_functions
                    self._last_ensure_stats["reused_existing"] = True
                    logger.info(
                        "♻️ [CACHE_REUSE] "
                        f"cache_name={cached_name} "
                        f"model_name={metadata.get('model_name')} "
                        f"created_at={metadata.get('created_at')}"
                    )
                    return cached_name
                if cached_name and cached_fingerprint != prompt_fingerprint:
                    logger.info(
                        "🧹 [CACHE_PROMPT_MISMATCH] "
                        f"cache_name={cached_name} "
                        f"stored_version={metadata.get('prompt_version')} "
                        f"current_version={CACHE_PROMPT_VERSION}"
                    )

            # Need to create new cache
            try:
                from ..core.ai import get_genai_client

                client = get_genai_client()
                if not client:
                    logger.warning("GenAI client not available, skipping cache creation")
                    return None

                logger.info(f"Converted {len(tool_functions)} tool functions to {len(gemini_tools)} Gemini tools for caching")
                tool_schema_chars = len(serialized_tool_schema)
                tool_schema_tokens = _count_tokens_with_sdk(client, model_name, serialized_tool_schema)
                system_prompt_tokens = _count_tokens_with_sdk(client, model_name, system_prompt)
                
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
                    ttl=f"{self._cache_ttl}s",
                    display_name=f"knowledgebot-system-{int(time.time())}",
                )

                logger.info(f"Creating Gemini cache (model: {model_name}, TTL: {self._cache_ttl}s)")
                self._last_ensure_stats["create_attempts"] += 1
                logger.info(
                    "🧱 [CACHE_CREATE_PAYLOAD] "
                    f"model={model_name} "
                    f"system_instruction_chars={len(system_prompt)} "
                    f"tools_count={len(gemini_tools) if gemini_tools else 0} "
                    f"tool_config_mode={'AUTO' if gemini_tools else 'none'} "
                    f"tool_schema_preview={serialized_tool_schema[:1500]}"
                )
                logger.info(f"Cache config includes:")
                logger.info(f"  - System instruction: {len(system_prompt)} chars")
                logger.info(f"  - System instruction tokens (sdk): {system_prompt_tokens if system_prompt_tokens is not None else 'unavailable'}")
                logger.info(f"  - Tools: {len(gemini_tools) if gemini_tools else 0} tool(s)")
                logger.info(f"  - Tool schema chars: {tool_schema_chars}")
                logger.info(f"  - Tool schema tokens (sdk): {tool_schema_tokens if tool_schema_tokens is not None else 'unavailable'}")
                logger.info(f"  - Tool calling mode: {'AUTO' if gemini_tools else 'none'}")
                if gemini_tools:
                    for tool in gemini_tools:
                        if hasattr(tool, 'function_declarations'):
                            logger.info(f"    - Tool functions: {[f.name for f in tool.function_declarations]}")
                
                cached_content = await client.aio.caches.create(
                    model=model_name,
                    config=cache_config,
                )
                logger.info(
                    "🧱 [CACHE_CREATE_RESULT] "
                    f"name={getattr(cached_content, 'name', None)} "
                    f"display_name={getattr(cached_content, 'display_name', None)} "
                    f"model={getattr(cached_content, 'model', None)} "
                    f"tool_count={len(getattr(cached_content, 'tools', None) or [])} "
                    f"tool_config={getattr(cached_content, 'tool_config', None)} "
                    f"usage_metadata={getattr(cached_content, 'usage_metadata', None)}"
                )

                old_cache_name = metadata.get("cache_name") if metadata else None
                if old_cache_name and old_cache_name != cached_content.name:
                    self._last_ensure_stats["recreated_remote"] = True
                    logger.info(f"Deleting superseded Gemini cache before switching active cache: {old_cache_name}")
                    await self._delete_remote_cache_by_name(old_cache_name)

                self._cache_name = cached_content.name
                self._cache_created_at = time.time()
                # Check if tools were actually cached (Gemini might ignore them)
                self._has_tools = len(getattr(cached_content, 'tools', None) or []) > 0
                
                # Store the system prompt and tools for reuse
                self._cached_system_prompt = system_prompt
                self._cached_tool_functions = tool_functions
                await self._store_metadata(
                    self._cache_name,
                    model_name,
                    has_tools=self._has_tools,
                    prompt_fingerprint=prompt_fingerprint,
                )

                logger.info(f"Created Gemini cache: {self._cache_name}")
                if cached_content.usage_metadata:
                    logger.info(f"Cached tokens: {cached_content.usage_metadata.total_token_count}")
                    logger.info(
                        f"🧭 [CACHE_TOKEN_BREAKDOWN] system_prompt_tokens_sdk={system_prompt_tokens if system_prompt_tokens is not None else 'unavailable'} "
                        f"tool_schema_tokens_sdk={tool_schema_tokens if tool_schema_tokens is not None else 'unavailable'} "
                        f"cached_total_tokens={cached_content.usage_metadata.total_token_count}"
                    )
                try:
                    cached_tokens = (
                        getattr(getattr(cached_content, "usage_metadata", None), "total_token_count", 0)
                        or (system_prompt_tokens or 0)
                        + (tool_schema_tokens or 0)
                    )
                    await track_model_usage(
                        provider="gemini",
                        model=model_name,
                        prompt_tokens=0,
                        completion_tokens=0,
                        total_tokens=cached_tokens,
                        api_call_type="cache_create",
                        request_metadata={
                            "cache_name": self._cache_name,
                            "cache_ttl_seconds": self._cache_ttl,
                            "cache_write_tokens": cached_tokens,
                            "system_prompt_tokens_sdk": system_prompt_tokens or 0,
                            "tool_schema_tokens_sdk": tool_schema_tokens or 0,
                            "tool_count": len(gemini_tools) if gemini_tools else 0,
                            "has_tools": self._has_tools,
                            "token_source": "gemini_cache_usage_metadata"
                            if getattr(cached_content, "usage_metadata", None)
                            else "sdk_count_tokens",
                        },
                    )
                except Exception as usage_error:
                    logger.warning(f"Failed to track Gemini cache creation usage: {usage_error}")
                
                return self._cache_name

            except Exception as e:
                error_str = str(e)
                self._last_ensure_stats["create_failures"] += 1
                self._last_ensure_stats["last_error"] = error_str[:240]
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
            self._cache_created_at = 0
            self._cached_system_prompt = None
            self._cached_tool_functions = None

            if cache_name:
                await self._delete_remote_cache_by_name(cache_name)

            client = await self._get_redis_client()
            await client.delete(REDIS_CACHE_METADATA_KEY)
            logger.info("🗃️ [CACHE_REDIS_DELETE] metadata_key_cleared=true")

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
        self._cache_created_at = 0
        if not keep_cached_content:
            self._cached_system_prompt = None
            self._cached_tool_functions = None
        logger.info(
            "🧹 [CACHE_LOCAL_INVALIDATE] "
            f"keep_cached_content={keep_cached_content}"
        )

    def get_cached_content(self) -> tuple[Optional[str], Optional[List[Callable]]]:
        """Get the cached system prompt and tool functions for reuse in fallback caches.
        
        Returns:
            Tuple of (system_prompt, tool_functions) or (None, None) if not available
        """
        return self._cached_system_prompt, self._cached_tool_functions


# Global singleton
gemini_cache_manager = GeminiCacheManager()
