"""
CachedGoogleModel - Subclass of Pydantic AI's GoogleModel for Gemini explicit context caching.

When google_cached_content is set in model_settings, the Gemini API returns 400 if
system_instruction, tools, or tool_config are also passed in the same request
(they must be IN the cache, not duplicated). This subclass strips those fields
from the GenerateContentConfig when a cache is active.

The Agent still has tools registered for EXECUTION (parsing + running tool calls).
Only the DECLARATIONS are stripped from the API request since they're in the cache.
"""

from typing import Any, cast

from pydantic_ai.models.google import GoogleModel, GoogleModelSettings
from pydantic_ai.models import ModelRequestParameters
from pydantic_ai.messages import ModelMessage
from shared.otel_logger import get_otel_logger

try:
    from google.genai.types import GenerateContentConfigDict, ContentUnionDict
except ImportError:
    pass

logger = get_otel_logger(__name__, "chatbot-orchestration")


class CachedGoogleModel(GoogleModel):
    """GoogleModel subclass that strips tools/system_instruction from API request when cache is active."""

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
