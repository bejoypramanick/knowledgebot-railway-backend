"""
GeminiCacheManager - Manages Gemini explicit context caching lifecycle.

Caches the system prompt + tool declarations so they don't need to be sent
with every request. Gemini gives a 90% discount on cached input tokens.

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

# Default cache TTL: 1 hour
DEFAULT_CACHE_TTL_SECONDS = 3600


class GeminiCacheManager:
    """Manages Gemini cached content lifecycle with hash-based invalidation."""

    def __init__(self):
        self._cache_name: Optional[str] = None
        self._cache_hash: Optional[str] = None
        self._cache_created_at: float = 0
        self._cache_ttl: int = int(os.getenv("GEMINI_CACHE_TTL_SECONDS", str(DEFAULT_CACHE_TTL_SECONDS)))
        self._lock = asyncio.Lock()

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
            logger.info(f"Gemini cache expired (elapsed: {elapsed:.0f}s, TTL: {self._cache_ttl}s)")
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

            # Reuse existing cache if hash matches and not expired
            if self.cache_name and self._cache_hash == content_hash:
                logger.info(f"Reusing existing Gemini cache: {self._cache_name} (hash: {content_hash})")
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
                logger.info(f"Converted {len(tool_functions)} tools to Gemini format for caching")

                # Create cached content
                from google.genai import types

                cache_config = types.CreateCachedContentConfig(
                    system_instruction=system_prompt,
                    tools=gemini_tools if gemini_tools else None,
                    ttl=f"{self._cache_ttl}s",
                    display_name=f"knowledgebot-system-{content_hash}",
                )

                logger.info(f"Creating Gemini cache (model: {model_name}, TTL: {self._cache_ttl}s, hash: {content_hash})")
                cached_content = await client.aio.caches.create(
                    model=model_name,
                    config=cache_config,
                )

                self._cache_name = cached_content.name
                self._cache_hash = content_hash
                self._cache_created_at = time.time()

                logger.info(f"Created Gemini cache: {self._cache_name}")
                if cached_content.usage_metadata:
                    logger.info(f"Cached tokens: {cached_content.usage_metadata.total_token_count}")

                return self._cache_name

            except Exception as e:
                logger.error(f"Failed to create Gemini cache: {e}", exc_info=True)
                logger.warning("Falling back to non-cached mode (agent works without cache)")
                return None

    def invalidate(self):
        """Clear the current cache (e.g. when persona changes)."""
        if self._cache_name:
            logger.info(f"Invalidating Gemini cache: {self._cache_name}")
        self._cache_name = None
        self._cache_hash = None
        self._cache_created_at = 0


# Global singleton
gemini_cache_manager = GeminiCacheManager()
