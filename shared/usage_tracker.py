"""
OpenAI Client Wrapper for Usage Tracking
Intercepts OpenAI API calls to capture and store token usage information.
"""
import logging
import openai
from typing import Any, Dict, Optional
from shared.token_tracker import track_openai_usage_from_response

logger = logging.getLogger(__name__)

# Store usage by thread/request to correlate with sessions
_thread_local_usage = {}

class TrackedOpenAIClient(openai.OpenAI):
    """OpenAI client wrapper that tracks token usage."""

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        logger.info("✅ TrackedOpenAIClient initialized")

    async def chat_completions_create(self, *args, **kwargs):
        """Intercept chat completion calls to track usage."""
        try:
            # Store session info if available (passed via kwargs)
            session_id = kwargs.pop('session_id', None)
            message_id = kwargs.pop('message_id', None)
            api_call_type = kwargs.pop('api_call_type', 'chat')

            # Make the actual API call
            response = await super().chat.completions.create(*args, **kwargs)

            # Extract and track usage information
            if hasattr(response, 'usage') and response.usage:
                logger.info(f"📊 Intercepted OpenAI usage: {response.usage}")
                try:
                    # Use MODEL_NAME from the calling context - we'll need to pass it
                    model_name = kwargs.get('model', 'gpt-4o')
                    await track_openai_usage_from_response(response.usage, session_id, message_id, api_call_type, model_name)
                    logger.info("✅ Usage tracked successfully")
                except Exception as e:
                    logger.error(f"❌ Failed to track usage: {e}")

            return response
        except Exception as e:
            logger.error(f"❌ Error in tracked chat completion: {e}")
            raise

    # Override the sync method too
    def chat_completions_create_sync(self, *args, **kwargs):
        """Intercept sync chat completion calls."""
        try:
            # Store session info if available
            session_id = kwargs.pop('session_id', None)
            message_id = kwargs.pop('message_id', None)
            api_call_type = kwargs.pop('api_call_type', 'chat')

            # Make the actual API call
            response = super().chat.completions.create(*args, **kwargs)

            # Extract and track usage information
            if hasattr(response, 'usage') and response.usage:
                logger.info(f"📊 Intercepted OpenAI usage (sync): {response.usage}")
                try:
                    model_name = kwargs.get('model', 'gpt-4o')
                    # For sync calls, we'll need to handle this differently
                    # For now, just log it
                    logger.info(f"📊 Usage would be tracked: {response.usage}")
                except Exception as e:
                    logger.error(f"❌ Failed to track usage (sync): {e}")

            return response
        except Exception as e:
            logger.error(f"❌ Error in tracked chat completion (sync): {e}")
            raise