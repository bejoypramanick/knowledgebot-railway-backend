import os
from shared.otel_logger import get_otel_logger

from google import genai
from pydantic_ai.models.google import GoogleModel

from chatbot_orchestration.core.config import settings

logger = get_otel_logger(__name__, "chatbot-orchestration")

# Global clients - initialized lazily
genai_client = None
gemini_model = None

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or settings.gemini_api_key
MODEL_NAME = os.getenv("CHATBOT_MODEL", settings.chatbot_model)

# Log configuration for debugging
logger.info(f"🔧 Gemini Configuration:")
logger.info(f"   GEMINI_API_KEY: {'✅ Set' if GEMINI_API_KEY else '❌ Missing'}")
logger.info(f"   CHATBOT_MODEL: {MODEL_NAME}")

def get_genai_client():
    """Lazy initialization of Gemini client."""
    global genai_client
    if genai_client is None and GEMINI_API_KEY:
        try:
            genai_client = genai.Client(api_key=GEMINI_API_KEY)
            logger.info("✅ Gemini client initialized")
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini client: {e}")
            genai_client = None
    elif genai_client is None and not GEMINI_API_KEY:
        logger.error("❌ GEMINI_API_KEY is not set - Gemini client cannot be initialized")
    return genai_client

# Initialize Gemini Model (used as fallback reference; agent_manager creates its own)
if GEMINI_API_KEY:
    try:
        gemini_model = GoogleModel(MODEL_NAME)
        logger.info(f"Gemini model '{MODEL_NAME}' initialized")
    except Exception as e:
        gemini_model = None
        logger.error(f"Failed to initialize GeminiModel '{MODEL_NAME}': {e}")
else:
    logger.warning("Gemini model not initialized - GEMINI_API_KEY is missing")

def get_gemini_model():
    """Get Gemini model with availability check"""
    if gemini_model is None:
        logger.warning("⚠️ Gemini model requested but not available - check GEMINI_API_KEY")
    return gemini_model
