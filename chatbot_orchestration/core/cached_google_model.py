"""
CachedGoogleModel - Subclass of Pydantic AI's GoogleModel for Gemini explicit context caching.

When google_cached_content is set in model_settings, the Gemini API returns 400 if
system_instruction, tools, or tool_config are also passed in the same request
(they must be IN the cache, not duplicated). This subclass strips those fields
from the GenerateContentConfig when a cache is active.

Resilience: If Google expires the cache before our local TTL detects it,
_generate_content catches the stale-cache error, invalidates the local cache,
rebuilds explicit cached content, and retries.

Resilience Patterns:
1. Exponential Backoff: Retries with jittered backoff for 503 errors
2. Model Fallback: Falls back to gemini-2.0-flash if gemini-2.5-flash-lite is unavailable
3. Circuit Breaker: Trips after 10 failures in 60s, blocks requests for 60s
"""

from collections.abc import AsyncIterator, Awaitable
from typing import Any, cast
import asyncio
import random
import time
from collections import deque

from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.messages import ModelMessage, BuiltinToolReturnPart, ToolReturnPart
from shared.otel_logger import get_otel_logger

# Import cache manager for fallback cache creation
from .cache_manager import GeminiCacheManager

try:
    from google.genai import errors as genai_errors
    from google.genai.types import (
        AutomaticFunctionCallingConfig,
        FunctionCallingConfig,
        FunctionCallingConfigMode,
        GenerateContentConfigDict,
        GenerateContentResponse,
        ContentUnionDict,
        ToolConfig,
    )
except ImportError:
    pass

logger = get_otel_logger(__name__, "chatbot-orchestration")


def _is_cache_error(error: Exception) -> bool:
    """Check if an error is related to a stale/expired/invalid cached_content reference."""
    msg = str(error).lower()
    # Handle SDK error codes and descriptions
    is_permission_denied = "403" in msg or "permission_denied" in msg or "permission denied" in msg
    is_not_found = "404" in msg or "not found" in msg or "not_found" in msg
    
    # Specific terms that imply a cache issue
    has_cache_terms = any(
        term in msg
        for term in (
            "cached_content",
            "cachedcontent",
            "cache",
            "expired",
        )
    )
    
    # Only treat as cache error if it explicitly mentions cache OR is a 403/404 with cache terms
    # We want to avoid catching generic "Resource Exhausted" 403s here.
    return has_cache_terms or ((is_permission_denied or is_not_found) and "cache" in msg)


def _is_quota_error(error: Exception) -> bool:
    """Check if error is a 429 Resource Exhausted or 403 Quota exceeded."""
    msg = str(error).lower()
    return any(
        term in msg
        for term in (
            "429",
            "resource_exhausted",
            "resource exhausted",
            "quota exceeded",
            "rate limit",
            "reached for tpm",
            "reached for rpm",
        )
    )


def _is_503_error(error: Exception) -> bool:
    """Check if error is a 503 Service Unavailable (high demand)."""
    msg = str(error).lower()
    return "503" in msg or "unavailable" in msg or "high demand" in msg


class CircuitBreaker:
    """Circuit breaker pattern for model-specific failures.

    Tracks failures per model. After threshold failures in window_seconds,
    trips the circuit and blocks requests for cooldown_seconds.
    """

    def __init__(
        self, threshold: int = 10, window_seconds: int = 60, cooldown_seconds: int = 60
    ):
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self._failures: dict[
            str, deque
        ] = {}  # model_name -> deque of failure timestamps
        self._tripped_until: dict[
            str, float
        ] = {}  # model_name -> timestamp when circuit closes

    def record_failure(self, model_name: str) -> None:
        """Record a failure for the given model."""
        now = time.time()

        if model_name not in self._failures:
            self._failures[model_name] = deque()

        # Add failure timestamp
        self._failures[model_name].append(now)

        # Remove failures outside the window
        cutoff = now - self.window_seconds
        while self._failures[model_name] and self._failures[model_name][0] < cutoff:
            self._failures[model_name].popleft()

        # Check if we should trip the circuit
        if len(self._failures[model_name]) >= self.threshold:
            self._tripped_until[model_name] = now + self.cooldown_seconds
            logger.warning(
                f"🔴 Circuit breaker TRIPPED for {model_name}: "
                f"{len(self._failures[model_name])} failures in {self.window_seconds}s. "
                f"Blocking requests for {self.cooldown_seconds}s"
            )

    def is_tripped(self, model_name: str) -> bool:
        """Check if circuit is tripped for the given model."""
        if model_name not in self._tripped_until:
            return False

        now = time.time()
        if now < self._tripped_until[model_name]:
            remaining = int(self._tripped_until[model_name] - now)
            logger.info(
                f"🔴 Circuit breaker is OPEN for {model_name} ({remaining}s remaining)"
            )
            return True

        # Circuit has cooled down
        logger.info(f"🟢 Circuit breaker CLOSED for {model_name} (cooldown complete)")
        del self._tripped_until[model_name]
        self._failures[model_name].clear()
        return False

    def reset(self, model_name: str) -> None:
        """Reset circuit breaker for a model (after successful request)."""
        if model_name in self._failures:
            self._failures[model_name].clear()
        if model_name in self._tripped_until:
            del self._tripped_until[model_name]


# Global circuit breaker instance
_circuit_breaker = CircuitBreaker(threshold=10, window_seconds=60, cooldown_seconds=60)


class CachedGoogleModel(GoogleModel):
    """GoogleModel subclass that strips tools/system_instruction from API request when cache is active.

    If the cache turns out to be stale (Google expired it), automatically retries
    after rebuilding explicit cached content.
    """

    async def _build_content_and_config(
        self,
        messages: list[ModelMessage],
        model_settings: GoogleModelSettings,
        model_request_parameters: ModelRequestParameters,
    ) -> tuple[list[ContentUnionDict], GenerateContentConfigDict]:
        contents, config = await super()._build_content_and_config(
            messages, model_settings, model_request_parameters
        )

        # Disable the Google GenAI SDK's Automatic Function Calling loop.
        # Pydantic AI already manages tool execution, and leaving SDK-level AFC enabled
        # causes repeated remote tool-call cycles (default maximum_remote_calls=10).
        config_dict = cast(dict[str, Any], config)
        config_dict["automatic_function_calling"] = AutomaticFunctionCallingConfig(
            disable=True,
            maximum_remote_calls=1,
        )
        has_tool_return = any(
            any(
                isinstance(part, (BuiltinToolReturnPart, ToolReturnPart))
                for part in getattr(msg, "parts", []) or []
            )
            for msg in messages
        )
        if model_settings.get("force_tool_calling") and not has_tool_return:
            logger.info("Force tool calling enabled for this request")
            config_dict["tool_config"] = ToolConfig(
                function_calling_config=FunctionCallingConfig(
                    mode=FunctionCallingConfigMode.ANY,
                    allowed_function_names=["search_knowledge_base"],
                )
            )
        elif model_settings.get("disable_tool_calling"):
            logger.info("Tool calling disabled for this request")
            config_dict["tool_config"] = ToolConfig(
                function_calling_config=FunctionCallingConfig(
                    mode=FunctionCallingConfigMode.NONE,
                )
            )
        config = cast(GenerateContentConfigDict, config_dict)
        logger.info(
            f"Gemini automatic_function_calling config: {config_dict.get('automatic_function_calling')}"
        )

        cached_content = model_settings.get("google_cached_content")
        if cached_content:
            # LATE-BINDING SYNCHRONIZATION:
            # The Agent may have been initialized with a stale cache ID (e.g. ID_OLD).
            # If a concurrent request or previous retry has already rebuilt the cache (ID_NEW),
            # we should use the new one instead of failing again with the old one.
            from .cache_manager import gemini_cache_manager
            
            live_cache_name = gemini_cache_manager.cache_name
            if live_cache_name and live_cache_name != cached_content:
                logger.info(f"🔄 Syncing stale cache reference: {cached_content} -> {live_cache_name}")
                cached_content = live_cache_name
                # Update settings so the REST of the pipeline (and super() if called) sees the new ID
                # Note: We cast to dict to ensure we can modify it (settings is typically a TypedDict)
                mutable_settings = cast(dict[str, Any], model_settings)
                mutable_settings["google_cached_content"] = live_cache_name

            logger.info(f"Gemini cache active: {cached_content}")
            logger.info(
                "Stripping system_instruction, tools, tool_config from API request (included in cache)"
            )

            if cached_content:
                # Log what tools were originally present before stripping
                original_tools = config.get("tools", [])
                if original_tools:
                    logger.info(
                        f"🔧 Original tools being stripped: {len(original_tools)} tool(s)"
                    )
                    for i, tool in enumerate(original_tools):
                        if hasattr(tool, "function_declarations"):
                            tool_names = [f.name for f in tool.function_declarations]
                            logger.info(f"   Tool {i + 1}: {tool_names}")
                else:
                    logger.warning(
                        "⚠️ No tools found in config to strip - this might be the issue!"
                    )

                # CRITICAL: Use pop() to REMOVE keys entirely, not set to None.
                # The Gemini API rejects requests that have system_instruction/tools
                # keys present at all (even as null) alongside cached_content.
                config_dict = cast(dict[str, Any], config)
                config_dict.pop("system_instruction", None)
                config_dict.pop("tools", None)
                config_dict.pop("tool_config", None)
                config = cast(GenerateContentConfigDict, config_dict)

                # DEEP DEFENSE: Some pydantic-ai versions might尝试将system prompt
                # 作为contents中的消息发送。Gemini API 严禁在有cache的情况下发送这些内容。
                sanitized_contents = []
                for content in (contents or []):
                    # In Gemini API, 'system' is not a valid role for contents (system_instruction is separate)
                    # but pydantic-ai might map it this way.
                    if isinstance(content, dict) and content.get("role") == "system":
                        logger.warning("🛡️ Deep strip: Removed role='system' Content from payload (cache active)")
                        continue
                    sanitized_contents.append(content)
                contents = sanitized_contents

        return contents, config

    async def _generate_content(
        self,
        messages: list[ModelMessage],
        stream: bool,
        model_settings: GoogleModelSettings,
        model_request_parameters: ModelRequestParameters,
    ) -> GenerateContentResponse | Awaitable[AsyncIterator[GenerateContentResponse]]:
        """Fail-fast Gemini call path with exactly ONE cache rebuild attempt.

        If the rebuilt cache also fails, raises a non-retryable RuntimeError
        to prevent pydantic-ai from looping back into more rebuilds.
        """
        # Guard: if we already tried rebuilding in this agent iteration, don't do it again.
        # pydantic-ai retries call _generate_content repeatedly — this flag prevents the loop.
        if getattr(self, '_cache_rebuild_attempted', False):
            cache_ref = model_settings.get("google_cached_content")
            logger.error(
                f"🚫 [CACHE_GUARD] Skipping rebuild — already attempted this iteration. "
                f"cache_ref={cache_ref}"
            )
            # Raise a RuntimeError (NOT a cache error) so pydantic-ai stops retrying
            raise RuntimeError(
                "Gemini cache rebuild already attempted and failed. "
                "The newly created cache was also rejected by Google. "
                "This may indicate an API key permission issue, model mismatch, or propagation delay."
            )

        try:
            result = await super()._generate_content(
                messages, stream, model_settings, model_request_parameters
            )
            # Success — reset the guard flag
            self._cache_rebuild_attempted = False
            return result
        except Exception as e:
            # ==================== DIAGNOSTIC LOGGING ====================
            import os as _os
            api_key = _os.getenv("GEMINI_API_KEY", "")
            api_key_info = f"{api_key[:8]}...{api_key[-4:]}" if len(api_key) > 12 else ("SET" if api_key else "MISSING")
            cache_ref = model_settings.get("google_cached_content")
            logger.error(
                f"🔍 [DIAG] _generate_content exception:\n"
                f"  exception_type={type(e).__name__}\n"
                f"  exception_str={str(e)[:500]}\n"
                f"  model_name={self.model_name}\n"
                f"  cache_ref={cache_ref}\n"
                f"  api_key={api_key_info}\n"
                f"  is_cache_error={_is_cache_error(e)}\n"
                f"  message_count={len(messages)}\n"
                f"  stream={stream}"
            )
            if e.__cause__:
                logger.error(f"🔍 [DIAG] __cause__: type={type(e.__cause__).__name__} str={str(e.__cause__)[:300]}")
            if hasattr(e, 'status_code'):
                logger.error(f"🔍 [DIAG] status_code={e.status_code}")
            if hasattr(e, 'body'):
                logger.error(f"🔍 [DIAG] body={e.body}")
            # ===========================================================

            # NEW: Handle Quota/Rate Limit errors BEFORE cache errors
            if _is_quota_error(e):
                logger.warning(
                    f"⚠️ [QUOTA_EXCEEDED] Gemini TPM/RPM limit hit. Waiting 5s... "
                    f"model={self.model_name}"
                )
                await asyncio.sleep( random.uniform(5.0, 7.0) ) # Smear retry to avoid thundering herd
                # Retry the same call. We don't increment the rebuild guard here
                # because the cache ID itself is likely perfectly fine.
                return await super()._generate_content(
                    messages, stream, model_settings, model_request_parameters
                )

            if not _is_cache_error(e):
                raise

            logger.warning(f"Gemini cached content rejected: {cache_ref} error={e}")

            # ==================== SINGLE REBUILD ATTEMPT ====================
            # Set the guard flag BEFORE rebuilding so that if pydantic-ai retries
            # after our rebuilt cache also fails, we don't enter the rebuild loop.
            self._cache_rebuild_attempted = True

            from .cache_manager import REDIS_CACHE_METADATA_KEY, gemini_cache_manager

            cached_system_prompt, cached_tool_functions = (
                gemini_cache_manager.get_cached_content()
            )
            if not cached_system_prompt or not cached_tool_functions:
                raise RuntimeError(
                    "Gemini cached content failed and no cached prompt/tools were available to rebuild it"
                ) from e

            gemini_cache_manager.invalidate(keep_cached_content=True)
            try:
                client = await gemini_cache_manager._get_redis_client()
                await client.delete(REDIS_CACHE_METADATA_KEY)
            except Exception as redis_error:
                logger.warning(
                    f"Failed to clear stale Gemini cache metadata from Redis: {redis_error}"
                )

            rebuilt_cache_name = await gemini_cache_manager.ensure_cache(
                system_prompt=cached_system_prompt,
                tool_functions=cached_tool_functions,
                model_name=self.model_name or "gemini-2.5-flash-lite",
            )
            if not rebuilt_cache_name:
                raise RuntimeError(
                    "Gemini cached content failed and remote cache rebuild returned no cache id"
                ) from e

            logger.info(
                f"Rebuilt Gemini cache after stale cache error: old={cache_ref} new={rebuilt_cache_name}"
            )

            # Retry ONCE with the rebuilt cache
            retry_settings = cast(dict[str, Any], dict(model_settings))
            retry_settings["google_cached_content"] = rebuilt_cache_name

            try:
                result = await super()._generate_content(
                    messages,
                    stream,
                    cast(GoogleModelSettings, retry_settings),
                    model_request_parameters,
                )
                # Rebuilt cache worked! Reset the guard flag.
                self._cache_rebuild_attempted = False
                logger.info(f"✅ Rebuilt cache {rebuilt_cache_name} succeeded on retry")
                return result
            except Exception as retry_error:
                # The REBUILT cache also failed. Log everything for diagnosis.
                logger.error(
                    f"🔍 [DIAG] REBUILT cache also failed!\n"
                    f"  rebuilt_cache_ref={rebuilt_cache_name}\n"
                    f"  old_cache_ref={cache_ref}\n"
                    f"  retry_exception_type={type(retry_error).__name__}\n"
                    f"  retry_exception_str={str(retry_error)[:500]}\n"
                    f"  is_cache_error={_is_cache_error(retry_error)}\n"
                    f"  model_name={self.model_name}\n"
                    f"  api_key={api_key_info}"
                )
                if hasattr(retry_error, 'status_code'):
                    logger.error(f"🔍 [DIAG] retry status_code={retry_error.status_code}")
                if hasattr(retry_error, 'body'):
                    logger.error(f"🔍 [DIAG] retry body={retry_error.body}")

                # Raise a NON-cache RuntimeError so pydantic-ai won't trigger another
                # rebuild cycle. The guard flag is already set as additional protection.
                raise RuntimeError(
                    f"Gemini cache rebuild failed: both old cache ({cache_ref}) and "
                    f"rebuilt cache ({rebuilt_cache_name}) were rejected by Google with 403. "
                    f"Retry error: {retry_error}"
                ) from retry_error

    async def _try_fallback_model(
        self,
        messages: list[ModelMessage],
        stream: bool,
        model_settings: GoogleModelSettings,
        model_request_parameters: ModelRequestParameters,
    ) -> GenerateContentResponse | Awaitable[AsyncIterator[GenerateContentResponse]]:
        """PATTERN 2: Model Fallback - Try a more stable model.

        Falls back from gemini-2.5-flash-lite to gemini-2.0-flash.

        CRITICAL: Gemini caches are model-specific. We must strip the cache
        reference when falling back to a different model, otherwise the API
        will reject the request (cache was created for the primary model).

        OPTIMIZATION: Creates a separate cache for fallback model using the same
        system prompt and tools to maintain performance benefits.

        The fallback must create a new explicit cache for the fallback model.
        Inline system prompting is not allowed.
        """
        primary_model = self.model_name or "gemini-2.5-flash-lite"
        fallback_model = "gemini-2.0-flash"

        logger.info(f"🔄 Falling back from {primary_model} to {fallback_model}")

        # CRITICAL: Strip google_cached_content from settings
        # Caches are model-specific and cannot be reused across different models
        fallback_settings = dict(model_settings)
        if "google_cached_content" in fallback_settings:
            cache_ref = fallback_settings.pop("google_cached_content")
            logger.info(
                f"⚠️ Removed primary cache reference {cache_ref} (cache is model-specific)"
            )

        # Try to create cache for fallback model using the EXACT same system prompt and tools
        # that were used for the primary cache
        fallback_cache_name = None

        try:
            logger.info("🔄 Attempting to create cache for fallback model...")

            # Get the exact system prompt and tools from the global cache manager
            from .cache_manager import gemini_cache_manager

            cached_system_prompt, cached_tool_functions = (
                gemini_cache_manager.get_cached_content()
            )

            if cached_system_prompt and cached_tool_functions:
                logger.info(
                    f"✅ Retrieved cached system prompt ({len(cached_system_prompt)} chars) and {len(cached_tool_functions)} tools"
                )

                # Create a separate cache manager instance for fallback
                fallback_cache_manager = GeminiCacheManager()

                fallback_cache_name = await fallback_cache_manager.ensure_cache(
                    system_prompt=cached_system_prompt,
                    tool_functions=cached_tool_functions,
                    model_name=fallback_model,
                )

                if fallback_cache_name:
                    logger.info(
                        f"✅ Created fallback cache with exact system prompt: {fallback_cache_name}"
                    )
                    # Add cache reference to fallback settings
                    fallback_settings["google_cached_content"] = fallback_cache_name
                else:
                    raise RuntimeError(
                        "Fallback cache creation returned None; refusing inline fallback"
                    )
            else:
                logger.warning(
                    "⚠️ Could not retrieve cached system prompt and tools from global cache manager"
                )
                raise RuntimeError(
                    "Could not retrieve cached system prompt and tools for fallback cache rebuild"
                )

        except Exception as cache_error:
            logger.error(f"⚠️ Fallback cache creation failed: {cache_error}")
            raise RuntimeError(
                "Fallback model requires explicit cache but cache rebuild failed"
            ) from cache_error

        logger.info("ℹ️ Fallback will use cached system_instruction + tools")

        logger.info("ℹ️ RAG search and all tools will function identically")

        fallback_settings = cast(GoogleModelSettings, fallback_settings)

        # Create a new instance with fallback model
        # Note: GoogleModel gets API key from environment, no need to pass it explicitly
        fallback_instance = CachedGoogleModel(fallback_model)

        try:
            # Use fallback settings (with or without cache reference)
            # The parent GoogleModel will automatically include system_instruction + tools
            # from the Agent's configuration if no cache is active
            result = await fallback_instance._generate_content_direct(
                messages, stream, fallback_settings, model_request_parameters
            )
            logger.info(f"✅ Fallback to {fallback_model} succeeded (cached mode)")
            return result
        except Exception as fallback_error:
            logger.error(
                f"❌ Fallback to {fallback_model} also failed: {fallback_error}"
            )
            # Return user-friendly error
            raise RuntimeError(
                f"Service temporarily unavailable due to high demand on {primary_model}. "
                f"Fallback to {fallback_model} also failed. Please try again in a moment."
            ) from fallback_error

    async def _generate_content_direct(
        self,
        messages: list[ModelMessage],
        stream: bool,
        model_settings: GoogleModelSettings,
        model_request_parameters: ModelRequestParameters,
    ) -> GenerateContentResponse | Awaitable[AsyncIterator[GenerateContentResponse]]:
        """Direct call to parent without retry logic (used by fallback)."""
        return await super()._generate_content(
            messages, stream, model_settings, model_request_parameters
        )
