"""Gemini AI client initialization for celery-file-worker."""
import os

from google import genai

from core.config import settings
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("genai_client", "celery-file-worker")

# Global clients - initialized lazily
genai_client = None

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY") or settings.gemini_api_key

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
