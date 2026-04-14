import os
from google import genai
from pydantic_ai.models.google import GoogleModel

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
    """Get the Gemini chat model."""
    model_name = os.getenv("CHATBOT_MODEL", settings.chatbot_model)
    
    logger.info(f"🤖 Initializing Gemini chat model: {model_name}")
    
    try:
        api_key = os.getenv("GEMINI_API_KEY") or settings.gemini_api_key
        if api_key and not os.getenv("GEMINI_API_KEY"):
            os.environ["GEMINI_API_KEY"] = api_key
        return GoogleModel(model_name)
    except Exception as e:
        logger.error(f"❌ Failed to initialize Gemini model {model_name}: {e}")
        return None
