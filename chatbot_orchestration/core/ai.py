import os
import logging

from google import genai
from pydantic_ai.models.google import GoogleModel, GoogleModelSettings

from chatbot_orchestration.core.config import settings

logger = logging.getLogger(__name__)

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

# Initialize Gemini Model with caching and reasoning logging
if GEMINI_API_KEY:
    try:
        logger.info(f"🔧 Attempting to initialize Gemini model: {MODEL_NAME}")
        # Pydantic AI's GeminiModel with 15-minute caching and reasoning logging
        gemini_model = GoogleModel(
            MODEL_NAME,
            settings=GoogleModelSettings(
                # Enable caching with 15-minute TTL
                cache_ttl=900,  # 15 minutes in seconds
                # Enable extended thinking for reasoning visibility (Gemini 2.0 feature)
                # This allows us to see the model's internal reasoning process
                thinking_config={
                    "type": "enabled",
                    "budget_tokens": 24000  # Allow substantial reasoning capacity
                } if "thinking" in os.environ.get("GEMINI_FEATURES", "").lower() else None
            )
        )
        thinking_status = "with reasoning logging" if os.environ.get("GEMINI_FEATURES", "").lower() else "without reasoning"
        logger.info(f"✅ Gemini model '{MODEL_NAME}' initialized with 15-minute caching {thinking_status}")
        if "thinking" in os.environ.get("GEMINI_FEATURES", "").lower():
            logger.info("   🧠 Extended thinking enabled - model reasoning will be logged")
    except Exception as e:
        gemini_model = None
        logger.error(f"❌ Failed to initialize GeminiModel '{MODEL_NAME}': {e}")
        logger.error(f"❌ Exception type: {type(e).__name__}")
        logger.error("Gemini model will be unavailable; chat endpoints may return 503 or degraded responses")
else:
    logger.warning("❌ Gemini model not initialized - GEMINI_API_KEY is missing")
    logger.warning("Chat endpoints will return 'AI service is currently unavailable'")

def get_gemini_model():
    """Get Gemini model with availability check"""
    if gemini_model is None:
        logger.warning("⚠️ Gemini model requested but not available - check GEMINI_API_KEY")
    return gemini_model
