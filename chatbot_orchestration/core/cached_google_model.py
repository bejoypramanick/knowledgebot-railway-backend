"""
CachedGoogleModel - Subclass of Pydantic AI's GoogleModel for Gemini explicit context caching.

When google_cached_content is set in model_settings, the Gemini API returns 400 if
system_instruction, tools, or tool_config are also passed in the same request
(they must be IN the cache, not duplicated). This subclass strips those fields
from the GenerateContentConfig when a cache is active.

Resilience: If Google expires the cache before our local TTL detects it,
_generate_content catches the stale-cache error, invalidates the local cache,
rebuilds the config WITH system_instruction/tools (inline fallback), and retries.

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
from pydantic_ai.messages import ModelMessage
from shared.otel_logger import get_otel_logger

# Import cache manager for fallback cache creation
from .cache_manager import GeminiCacheManager

try:
    from google.genai import errors as genai_errors
    from google.genai.types import (
        GenerateContentConfigDict,
        GenerateContentResponse,
        ContentUnionDict,
    )
except ImportError:
    pass

logger = get_otel_logger(__name__, "chatbot-orchestration")


def _is_cache_error(error: Exception) -> bool:
    """Check if an error is related to a stale/expired/invalid cached_content reference."""
    msg = str(error).lower()
    return any(term in msg for term in (
        'cached_content', 'cachedcontent', 'cache', 'not found', 'expired',
    ))


def _is_503_error(error: Exception) -> bool:
    """Check if error is a 503 Service Unavailable (high demand)."""
    msg = str(error).lower()
    return '503' in msg or 'unavailable' in msg or 'high demand' in msg


class CircuitBreaker:
    """Circuit breaker pattern for model-specific failures.
    
    Tracks failures per model. After threshold failures in window_seconds,
    trips the circuit and blocks requests for cooldown_seconds.
    """
    
    def __init__(self, threshold: int = 10, window_seconds: int = 60, cooldown_seconds: int = 60):
        self.threshold = threshold
        self.window_seconds = window_seconds
        self.cooldown_seconds = cooldown_seconds
        self._failures: dict[str, deque] = {}  # model_name -> deque of failure timestamps
        self._tripped_until: dict[str, float] = {}  # model_name -> timestamp when circuit closes
        
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
            logger.info(f"🔴 Circuit breaker is OPEN for {model_name} ({remaining}s remaining)")
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
    without cache so the request succeeds with inline system_instruction + tools.
    """

    async def _build_content_and_config(
        self,
        messages: list[ModelMessage],
        model_settings: GoogleModelSettings,
        model_request_parameters: ModelRequestParameters,
    ) -> tuple[list[ContentUnionDict], GenerateContentConfigDict]:
        contents, config = await super()._build_content_and_config(messages, model_settings, model_request_parameters)

        cached_content = model_settings.get('google_cached_content')
        if cached_content:
            logger.info(f"Gemini cache active: {cached_content}")
            logger.info("Stripping system_instruction, tools, tool_config from API request (included in cache)")
            
            # INSPECT CACHED CONTENT - Retrieve and log what's actually in the cache
            try:
                from ..core.ai import get_genai_client
                client = get_genai_client()
                if client:
                    logger.info("🔍 INSPECTING GEMINI CACHE CONTENTS...")
                    cached_data = await client.aio.caches.get(name=cached_content)
                    
                    logger.info("=" * 80)
                    logger.info("📋 CACHED CONTENT INSPECTION")
                    logger.info("=" * 80)
                    logger.info(f"Cache Name: {cached_data.name}")
                    logger.info(f"Display Name: {cached_data.display_name}")
                    logger.info(f"Model: {cached_data.model}")
                    
                    # Check if state attribute exists (API might have changed)
                    if hasattr(cached_data, 'state'):
                        logger.info(f"State: {cached_data.state}")
                    else:
                        logger.info("State: Not available (API change)")
                    
                    # Check other optional attributes
                    if hasattr(cached_data, 'create_time'):
                        logger.info(f"Create Time: {cached_data.create_time}")
                    if hasattr(cached_data, 'update_time'):
                        logger.info(f"Update Time: {cached_data.update_time}")
                    if hasattr(cached_data, 'expire_time'):
                        logger.info(f"Expire Time: {cached_data.expire_time}")
                    
                    if cached_data.usage_metadata:
                        logger.info(f"Total Token Count: {cached_data.usage_metadata.total_token_count}")
                    
                    # Check system instruction
                    has_system_instruction = bool(getattr(cached_data, "system_instruction", None))
                    if hasattr(cached_data, 'system_instruction') and cached_data.system_instruction:
                        sys_inst_len = len(str(cached_data.system_instruction))
                        logger.info(f"✅ System Instruction: {sys_inst_len} chars")
                        # Log first 200 chars to verify it's the right prompt
                        sys_preview = str(cached_data.system_instruction)[:200]
                        logger.info(f"   Preview: {sys_preview}...")
                    else:
                        logger.warning("❌ No system instruction found in cache!")
                    
                    # Check tools - this is the critical part
                    has_tools = bool(getattr(cached_data, "tools", None))
                    if hasattr(cached_data, 'tools') and cached_data.tools:
                        logger.info(f"✅ Tools in cache: {len(cached_data.tools)} tool(s)")
                        for i, tool in enumerate(cached_data.tools):
                            logger.info(f"   Tool {i+1}:")
                            if hasattr(tool, 'function_declarations'):
                                logger.info(f"     Function declarations: {len(tool.function_declarations)}")
                                for j, func_decl in enumerate(tool.function_declarations):
                                    logger.info(f"       Function {j+1}: {func_decl.name}")
                                    logger.info(f"         Description: {func_decl.description}")
                                    if hasattr(func_decl, 'parameters') and func_decl.parameters:
                                        params = func_decl.parameters
                                        if hasattr(params, 'properties') and params.properties:
                                            param_names = list(params.properties.keys())
                                            logger.info(f"         Parameters: {param_names}")
                                        if hasattr(params, 'required') and params.required:
                                            logger.info(f"         Required: {params.required}")
                            else:
                                logger.info(f"     No function declarations found")
                    else:
                        logger.error("🚨 CRITICAL: NO TOOLS FOUND IN CACHE!")
                        logger.error("🚨 This explains why the agent isn't calling search_knowledge_base!")
                        logger.error("🚨 The cache was created without tools or tools were lost!")

                    # If cache is missing critical parts, DO NOT proceed with tool calls.
                    # Deterministic policy (per product requirement):
                    # - Invalidate + rebuild cache
                    # - Only then proceed in cached mode (tools/system prompt must come from cache)
                    if not has_system_instruction or not has_tools:
                        logger.error("🚨 Invalid Gemini cache detected (missing system_instruction/tools). Rebuilding cache before continuing.")
                        from .cache_manager import gemini_cache_manager
                        cached_system_prompt, cached_tool_functions = gemini_cache_manager.get_cached_content()
                        if not cached_system_prompt or not cached_tool_functions:
                            raise RuntimeError(
                                "Gemini cache is invalid and no cached system_prompt/tools are available to rebuild it"
                            )
                        # Clear the broken cache reference but keep the cached prompt/tools for rebuild.
                        gemini_cache_manager.invalidate(keep_cached_content=True)

                        model_name = getattr(self, "model_name", None) or model_settings.get("model") or "gemini-2.5-flash-lite"
                        rebuilt_cache_name = await gemini_cache_manager.ensure_cache(
                            system_prompt=cached_system_prompt,
                            tool_functions=cached_tool_functions,
                            model_name=model_name,
                        )
                        if not rebuilt_cache_name:
                            raise RuntimeError("Gemini cache rebuild failed; refusing to continue without cached tools")

                        # IMPORTANT: we must rebuild the request config using the *new* cached_content,
                        # but still run through our stripping logic (can't return super() directly).
                        rebuilt_once = bool(model_settings.get("_gemini_cache_rebuilt_once"))
                        if rebuilt_once:
                            raise RuntimeError("Gemini cache rebuild loop detected; refusing to continue")

                        model_settings = dict(model_settings)
                        model_settings["_gemini_cache_rebuilt_once"] = True
                        model_settings["google_cached_content"] = rebuilt_cache_name
                        return await self._build_content_and_config(
                            messages,
                            cast(GoogleModelSettings, model_settings),
                            model_request_parameters,
                        )
                    
                    logger.info("=" * 80)
                else:
                    logger.warning("GenAI client not available for cache inspection")
            except Exception as inspect_error:
                logger.error(f"Failed to inspect cache contents: {inspect_error}")
                # Deterministic policy: if we can't verify cached tools/system prompt, rebuild cache.
                from .cache_manager import gemini_cache_manager
                cached_system_prompt, cached_tool_functions = gemini_cache_manager.get_cached_content()
                if not cached_system_prompt or not cached_tool_functions:
                    raise RuntimeError(
                        "Gemini cache inspection failed and no cached system_prompt/tools are available to rebuild it"
                    )
                gemini_cache_manager.invalidate(keep_cached_content=True)
                model_name = getattr(self, "model_name", None) or model_settings.get("model") or "gemini-2.5-flash-lite"
                rebuilt_cache_name = await gemini_cache_manager.ensure_cache(
                    system_prompt=cached_system_prompt,
                    tool_functions=cached_tool_functions,
                    model_name=model_name,
                )
                if not rebuilt_cache_name:
                    raise RuntimeError("Gemini cache rebuild failed after inspection error; refusing to continue without cached tools")
                rebuilt_once = bool(model_settings.get("_gemini_cache_rebuilt_once"))
                if rebuilt_once:
                    raise RuntimeError("Gemini cache rebuild loop detected after inspection error; refusing to continue")
                model_settings = dict(model_settings)
                model_settings["_gemini_cache_rebuilt_once"] = True
                model_settings["google_cached_content"] = rebuilt_cache_name
                return await self._build_content_and_config(
                    messages,
                    cast(GoogleModelSettings, model_settings),
                    model_request_parameters,
                )
            
            if cached_content:
                # Log what tools were originally present before stripping
                original_tools = config.get('tools', [])
                if original_tools:
                    logger.info(f"🔧 Original tools being stripped: {len(original_tools)} tool(s)")
                    for i, tool in enumerate(original_tools):
                        if hasattr(tool, 'function_declarations'):
                            tool_names = [f.name for f in tool.function_declarations]
                            logger.info(f"   Tool {i+1}: {tool_names}")
                else:
                    logger.warning("⚠️ No tools found in config to strip - this might be the issue!")

                # CRITICAL: Use pop() to REMOVE keys entirely, not set to None.
                # The Gemini API rejects requests that have system_instruction/tools
                # keys present at all (even as null) alongside cached_content.
                config_dict = cast(dict[str, Any], config)
                config_dict.pop('system_instruction', None)
                config_dict.pop('tools', None)
                config_dict.pop('tool_config', None)

                config = cast(GenerateContentConfigDict, config_dict)

        return contents, config

    async def _generate_content(
        self,
        messages: list[ModelMessage],
        stream: bool,
        model_settings: GoogleModelSettings,
        model_request_parameters: ModelRequestParameters,
    ) -> GenerateContentResponse | Awaitable[AsyncIterator[GenerateContentResponse]]:
        """Override to add resilience patterns:
        
        1. Exponential Backoff: Retries with jittered backoff for 503 errors
        2. Model Fallback: Falls back to gemini-2.0-flash if primary model unavailable
        3. Circuit Breaker: Trips after 10 failures in 60s, blocks for 60s
        
        If the cached_content reference is expired/invalid on Google's side,
        catch the error, invalidate local cache, rebuild config without cache,
        and retry with inline system_instruction + tools.
        """
        
        # Get model name from settings or use default
        model_name = self.model_name or "gemini-2.5-flash-lite"
        
        # PATTERN 3: Circuit Breaker - Check if circuit is tripped
        if _circuit_breaker.is_tripped(model_name):
            logger.warning(f"Circuit breaker is OPEN for {model_name}, attempting fallback...")
            # Try fallback model immediately
            return await self._try_fallback_model(messages, stream, model_settings, model_request_parameters)
        
        # PATTERN 1: Exponential Backoff with retries
        max_retries = 3
        for attempt in range(max_retries):
            try:
                result = await super()._generate_content(messages, stream, model_settings, model_request_parameters)
                
                # Success! Reset circuit breaker
                _circuit_breaker.reset(model_name)
                return result
                
            except Exception as e:
                error_msg = str(e)
                
                # Handle cache errors (existing logic)
                cached_content = model_settings.get('google_cached_content')
                if cached_content and _is_cache_error(e):
                    logger.warning(f"Stale Gemini cache detected ({cached_content}): {e}")
                    logger.info("Invalidating cache and rebuilding before retrying (no inline fallback)")

                    from .cache_manager import gemini_cache_manager

                    # Preserve cached prompt/tools so we can deterministically rebuild.
                    cached_system_prompt, cached_tool_functions = gemini_cache_manager.get_cached_content()
                    gemini_cache_manager.invalidate(keep_cached_content=True)

                    if not cached_system_prompt or not cached_tool_functions:
                        raise RuntimeError(
                            "Gemini cache is stale/invalid and no cached system_prompt/tools are available to rebuild it"
                        )

                    model_name_for_cache = model_settings.get("model") or self.model_name or "gemini-2.5-flash-lite"
                    rebuilt_cache_name = await gemini_cache_manager.ensure_cache(
                        system_prompt=cached_system_prompt,
                        tool_functions=cached_tool_functions,
                        model_name=model_name_for_cache,
                    )
                    if not rebuilt_cache_name:
                        raise RuntimeError("Gemini cache rebuild failed after cache error; refusing inline fallback")

                    refreshed_settings = dict(model_settings)
                    refreshed_settings["google_cached_content"] = rebuilt_cache_name
                    refreshed_settings = cast(GoogleModelSettings, refreshed_settings)

                    logger.info(f"Retrying request with rebuilt cache: {rebuilt_cache_name}")
                    return await super()._generate_content(messages, stream, refreshed_settings, model_request_parameters)
                
                # PATTERN 1 & 3: Handle 503 errors with exponential backoff
                if _is_503_error(e):
                    _circuit_breaker.record_failure(model_name)
                    
                    # Check if circuit just tripped
                    if _circuit_breaker.is_tripped(model_name):
                        logger.error(f"Circuit breaker TRIPPED for {model_name} after 503 error")
                        # Try fallback immediately
                        return await self._try_fallback_model(messages, stream, model_settings, model_request_parameters)
                    
                    # Exponential backoff with jitter
                    if attempt < max_retries - 1:
                        wait_time = (2 ** attempt) + random.uniform(0, 1)
                        logger.warning(
                            f"503 detected for {model_name} (attempt {attempt + 1}/{max_retries}), "
                            f"retrying in {wait_time:.2f}s... Error: {error_msg[:200]}"
                        )
                        await asyncio.sleep(wait_time)
                        continue
                    else:
                        # All retries exhausted, try fallback
                        logger.error(f"All retries exhausted for {model_name}, attempting fallback...")
                        return await self._try_fallback_model(messages, stream, model_settings, model_request_parameters)
                
                # Other errors - record failure and propagate
                _circuit_breaker.record_failure(model_name)
                raise
        
        # Should never reach here, but just in case
        raise RuntimeError(f"Unexpected state in _generate_content after {max_retries} attempts")
    
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
        
        The fallback will use either:
        - Cached mode: If fallback cache creation succeeds
        - Inline mode: If cache creation fails (system_instruction + tools)
        
        This ensures RAG search and all tool functionality works identically in fallback mode.
        """
        primary_model = self.model_name or "gemini-2.5-flash-lite"
        fallback_model = "gemini-2.0-flash"
        
        logger.info(f"🔄 Falling back from {primary_model} to {fallback_model}")
        
        # CRITICAL: Strip google_cached_content from settings
        # Caches are model-specific and cannot be reused across different models
        fallback_settings = dict(model_settings)
        if 'google_cached_content' in fallback_settings:
            cache_ref = fallback_settings.pop('google_cached_content')
            logger.info(f"⚠️ Removed primary cache reference {cache_ref} (cache is model-specific)")
        
        # Try to create cache for fallback model using the EXACT same system prompt and tools
        # that were used for the primary cache
        fallback_cache_name = None
        
        try:
            logger.info("🔄 Attempting to create cache for fallback model...")
            
            # Get the exact system prompt and tools from the global cache manager
            from .cache_manager import gemini_cache_manager
            cached_system_prompt, cached_tool_functions = gemini_cache_manager.get_cached_content()
            
            if cached_system_prompt and cached_tool_functions:
                logger.info(f"✅ Retrieved cached system prompt ({len(cached_system_prompt)} chars) and {len(cached_tool_functions)} tools")
                
                # Create a separate cache manager instance for fallback
                fallback_cache_manager = GeminiCacheManager()
                
                fallback_cache_name = await fallback_cache_manager.ensure_cache(
                    system_prompt=cached_system_prompt,
                    tool_functions=cached_tool_functions,
                    model_name=fallback_model,
                )
                
                if fallback_cache_name:
                    logger.info(f"✅ Created fallback cache with exact system prompt: {fallback_cache_name}")
                    # Add cache reference to fallback settings
                    fallback_settings['google_cached_content'] = fallback_cache_name
                else:
                    logger.info("ℹ️ Fallback cache creation returned None, using inline mode")
            else:
                logger.warning("⚠️ Could not retrieve cached system prompt and tools from global cache manager")
                logger.info("ℹ️ This may happen if primary cache was not created or expired")
                logger.info("ℹ️ Fallback will use inline mode with system_instruction + tools from Agent")
                
        except Exception as cache_error:
            logger.warning(f"⚠️ Fallback cache creation failed: {cache_error}, using inline mode")
            fallback_cache_name = None
        
        if fallback_cache_name:
            logger.info("ℹ️ Fallback will use cached system_instruction + tools")
        else:
            logger.info("ℹ️ Fallback will use inline system_instruction + tools (no cache)")
            logger.info("ℹ️ Note: Fallback may have slightly higher token usage due to no cache")
        
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
            cache_mode = "cached" if fallback_cache_name else "inline"
            logger.info(f"✅ Fallback to {fallback_model} succeeded ({cache_mode} mode)")
            return result
        except Exception as fallback_error:
            logger.error(f"❌ Fallback to {fallback_model} also failed: {fallback_error}")
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
        return await super()._generate_content(messages, stream, model_settings, model_request_parameters)
