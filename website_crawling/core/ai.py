import os
from shared.logging_config import get_railway_logger
import logging
from google import genai
from shared.config import settings

logger = get_railway_logger(__name__)

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")

# Global client
genai_client = None

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
