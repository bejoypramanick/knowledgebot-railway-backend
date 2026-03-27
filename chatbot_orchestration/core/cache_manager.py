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
import os
import time
from typing import Callable, List, Optional

from shared.otel_logger import get_otel_logger

logger = get_otel_logger(__name__, "chatbot-orchestration")

# Default cache TTL: 10 minutes (safety net — cache is explicitly deleted on last session close)
DEFAULT_CACHE_TTL_SECONDS = 600


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

            # Check for force refresh environment variable
            force_refresh = os.getenv("FORCE_CACHE_REFRESH", "false").lower() == "true"
            if force_refresh:
                logger.warning("🔄 FORCE_CACHE_REFRESH=true - forcing cache recreation")
                self._cache_name = None
                self._cache_hash = None

            # Reuse existing cache if hash matches and not expired
            if self.cache_name and self._cache_hash == content_hash and not force_refresh:
                logger.info(f"Reusing existing Gemini cache: {self._cache_name} (hash: {content_hash})")
                # Preserve prompt/tools so we can deterministically rebuild if the cache turns out to be
                # missing system_instruction/tools (or Google returns a cache error).
                self._cached_system_prompt = system_prompt
                self._cached_tool_functions = tool_functions
                return self._cache_name

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
                            mode=types.FunctionCallingConfigMode.ANY,
                            allowed_function_names=["search_knowledge_base"],
                        )
                    ) if gemini_tools else None,
                    ttl=f"{self._cache_ttl}s",
                    display_name=f"knowledgebot-system-{content_hash}",
                )

                logger.info(f"Creating Gemini cache (model: {model_name}, TTL: {self._cache_ttl}s, hash: {content_hash})")
                logger.info(f"Cache config includes:")
                logger.info(f"  - System instruction: {len(system_prompt)} chars")
                logger.info(f"  - Tools: {len(gemini_tools) if gemini_tools else 0} tool(s)")
                logger.info(f"  - Forced tool calling: {'yes' if gemini_tools else 'no'}")
                if gemini_tools:
                    for tool in gemini_tools:
                        if hasattr(tool, 'function_declarations'):
                            logger.info(f"    - Tool functions: {[f.name for f in tool.function_declarations]}")
                
                cached_content = await client.aio.caches.create(
                    model=model_name,
                    config=cache_config,
                )

                self._cache_name = cached_content.name
                self._cache_hash = content_hash
                self._cache_created_at = time.time()
                # Store the system prompt and tools for reuse
                self._cached_system_prompt = system_prompt
                self._cached_tool_functions = tool_functions

                logger.info(f"Created Gemini cache: {self._cache_name}")
                if cached_content.usage_metadata:
                    logger.info(f"Cached tokens: {cached_content.usage_metadata.total_token_count}")
                
                # DEBUG: Immediately inspect the cache we just created
                debug_cache = os.getenv("DEBUG_GEMINI_CACHE", "false").lower() == "true"
                if debug_cache:
                    logger.info("🔍 DEBUG_GEMINI_CACHE enabled - inspecting newly created cache...")
                    inspection = await self.inspect_cache()
                    logger.info("=" * 80)
                    logger.info("🔍 CACHE CREATION VERIFICATION")
                    logger.info("=" * 80)
                    for key, value in inspection.items():
                        if key == "tool_functions":
                            logger.info(f"{key}: {len(value)} functions")
                            for func in value:
                                logger.info(f"  - {func['name']}: {func['description']}")
                        else:
                            logger.info(f"{key}: {value}")
                    logger.info("=" * 80)

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
            cache_name = self._cache_name
            if not cache_name:
                return

            # Clear local state first (so no request tries to use it mid-delete)
            self._cache_name = None
            self._cache_hash = None
            self._cache_created_at = 0
            self._cached_system_prompt = None
            self._cached_tool_functions = None

            try:
                from ..core.ai import get_genai_client

                client = get_genai_client()
                if not client:
                    logger.warning("GenAI client not available, cannot delete cache")
                    return

                await client.aio.caches.delete(name=cache_name)
                logger.info(f"Deleted Gemini cache from Google: {cache_name} (billing stopped)")

            except Exception as e:
                # Cache may already be expired/deleted on Google's side — that's fine
                logger.warning(f"Could not delete Gemini cache {cache_name}: {e}")

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

    async def inspect_cache(self) -> dict:
        """Inspect the current cache contents for debugging.
        
        Returns:
            Dictionary with cache inspection results
        """
        if not self.cache_name:
            return {"error": "No active cache"}
        
        try:
            from ..core.ai import get_genai_client
            client = get_genai_client()
            if not client:
                return {"error": "GenAI client not available"}
            
            cached_data = await client.aio.caches.get(name=self.cache_name)
            
            inspection = {
                "cache_name": cached_data.name,
                "display_name": cached_data.display_name,
                "model": cached_data.model,
                "state": getattr(cached_data, 'state', 'Not available'),
                "create_time": str(getattr(cached_data, 'create_time', 'Not available')),
                "update_time": str(getattr(cached_data, 'update_time', 'Not available')),
                "expire_time": str(getattr(cached_data, 'expire_time', 'Not available')),
                "has_system_instruction": bool(hasattr(cached_data, 'system_instruction') and cached_data.system_instruction),
                "tools_count": 0,
                "tool_functions": []
            }
            
            if cached_data.usage_metadata:
                inspection["total_token_count"] = cached_data.usage_metadata.total_token_count
            
            if hasattr(cached_data, 'system_instruction') and cached_data.system_instruction:
                inspection["system_instruction_length"] = len(str(cached_data.system_instruction))
                inspection["system_instruction_preview"] = str(cached_data.system_instruction)[:200]
            
            if hasattr(cached_data, 'tools') and cached_data.tools:
                inspection["tools_count"] = len(cached_data.tools)
                for tool in cached_data.tools:
                    if hasattr(tool, 'function_declarations'):
                        for func_decl in tool.function_declarations:
                            inspection["tool_functions"].append({
                                "name": func_decl.name,
                                "description": func_decl.description,
                                "parameters": list(func_decl.parameters.properties.keys()) if hasattr(func_decl, 'parameters') and func_decl.parameters and hasattr(func_decl.parameters, 'properties') else []
                            })
            
            return inspection
            
        except Exception as e:
            return {"error": f"Failed to inspect cache: {e}"}


# Global singleton
gemini_cache_manager = GeminiCacheManager()
