import os
from google import genai
from pydantic_ai.models.google import GoogleModel
from pydantic_ai.models.openai import OpenAIModel
from pydantic_ai.models.anthropic import AnthropicModel

from shared.otel_logger import get_otel_logger
from chatbot_orchestration.core.config import settings

logger = get_otel_logger(__name__, "chatbot-orchestration")

# Global clients - initialized lazily
_genai_client = None

def get_genai_client():
    """Lazy initialization of Gemini client (used for embeddings/tools)."""
    global _genai_client
    api_key = os.getenv("GEMINI_API_KEY") or settings.gemini_api_key
    if _genai_client is None and api_key:
        try:
            _genai_client = genai.Client(api_key=api_key)
            logger.info("✅ Gemini client initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini client: {e}")
    return _genai_client

def get_model():
    """Get the Pydantic AI model based on provider configuration."""
    provider = os.getenv("CHATBOT_PROVIDER", settings.chatbot_provider).lower()
    model_name = os.getenv("CHATBOT_MODEL", settings.chatbot_model)
    
    logger.info(f"🤖 Initializing model provider: {provider} ({model_name})")
    
    try:
        if provider == "google":
            api_key = os.getenv("GEMINI_API_KEY") or settings.gemini_api_key
            return GoogleModel(model_name, api_key=api_key)
        elif provider == "openai":
            api_key = os.getenv("OPENAI_API_KEY") or settings.openai_api_key
            return OpenAIModel(model_name, api_key=api_key)
        elif provider == "anthropic":
            api_key = os.getenv("ANTHROPIC_API_KEY") or settings.anthropic_api_key
            return AnthropicModel(model_name, api_key=api_key)
        else:
            logger.warning(f"⚠️ Unknown provider '{provider}', falling back to Google")
            return GoogleModel(model_name, api_key=os.getenv("GEMINI_API_KEY") or settings.gemini_api_key)
    except Exception as e:
        logger.error(f"❌ Failed to initialize model {model_name} for {provider}: {e}")
        return None
