"""
CachedGoogleModel - Subclass of Pydantic AI's GoogleModel for Gemini explicit context caching.

When google_cached_content is set in model_settings, the Gemini API returns 400 if
system_instruction, tools, or tool_config are also passed in the same request
(they must be IN the cache, not duplicated). This subclass strips those fields
from the GenerateContentConfig when a cache is active.

Resilience: If Google expires the cache before our local TTL detects it,
_generate_content catches the stale-cache error, invalidates the local cache,
rebuilds the config WITH system_instruction/tools (inline fallback), and retries.
"""

from collections.abc import AsyncIterator, Awaitable
from typing import Any, cast

from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.messages import ModelMessage
from shared.otel_logger import get_otel_logger

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
        contents, config = await super()._build_content_and_config(
            messages, model_settings, model_request_parameters
        )

        cached_content = model_settings.get('google_cached_content')
        if cached_content:
            logger.info(f"Gemini cache active: {cached_content}")
            logger.info("Stripping system_instruction, tools, tool_config from API request (included in cache)")

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
        """Override to add stale-cache resilience.

        If the cached_content reference is expired/invalid on Google's side,
        catch the error, invalidate local cache, rebuild config without cache,
        and retry with inline system_instruction + tools.
        """
        try:
            return await super()._generate_content(messages, stream, model_settings, model_request_parameters)
        except Exception as e:
            cached_content = model_settings.get('google_cached_content')
            if not cached_content or not _is_cache_error(e):
                raise  # Not cache-related, propagate normally

            logger.warning(f"Stale Gemini cache detected ({cached_content}): {e}")
            logger.info("Invalidating cache and retrying with inline system_instruction + tools")

            # Invalidate local cache so future requests don't hit this again
            from .cache_manager import gemini_cache_manager
            gemini_cache_manager.invalidate()

            # Strip google_cached_content from settings and retry
            # This causes _build_content_and_config to keep system_instruction/tools intact
            fallback_settings = dict(model_settings)
            fallback_settings.pop('google_cached_content', None)
            fallback_settings = cast(GoogleModelSettings, fallback_settings)

            logger.info("Retrying request without cache (inline fallback)")
            return await super()._generate_content(messages, stream, fallback_settings, model_request_parameters)
