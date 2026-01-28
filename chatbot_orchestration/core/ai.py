import os
import logging
from google import genai
from pydantic_ai.models.google import GoogleModel
from shared.config import settings

logger = logging.getLogger(__name__)

# Global clients - initialized lazily
genai_client = None
gemini_model = None

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or settings.gemini_api_key
MODEL_NAME = os.getenv("CHATBOT_MODEL", settings.chatbot_model)

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
    return genai_client

# Initialize Gemini Model
if GEMINI_API_KEY:
    try:
        # Pydantic AI's GeminiModel
        gemini_model = GoogleModel(MODEL_NAME)
        logger.info("✅ Gemini model initialized")
    except Exception as e:
        gemini_model = None
        logger.error(f"❌ Failed to initialize GeminiModel: {e}")
        logger.error("Gemini model will be unavailable; chat endpoints may return 503 or degraded responses")
else:
    logger.warning("Gemini model not initialized - GEMINI_API_KEY is missing")

def get_gemini_model():
    return gemini_model
