import os
import asyncio
from typing import List, Optional
from shared.otel_logger import get_otel_logger
# Configuration from environment variables with defaults
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "google").lower()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-004")

logger = get_otel_logger("embeddings", "shared")

# Lazy clients
_genai_client = None

def get_genai_client():
    from google import genai
    global _genai_client
    api_key = os.getenv("GEMINI_API_KEY") or GEMINI_API_KEY
    if _genai_client is None and api_key:
        try:
            _genai_client = genai.Client(api_key=api_key)
        except Exception as e:
            logger.error(f"❌ Failed to initialize Gemini client for embeddings: {e}")
    return _genai_client

async def generate_embedding(query: str) -> List[float]:
    """Generate an embedding vector using the configured provider."""
    provider = os.getenv("EMBEDDING_PROVIDER", EMBEDDING_PROVIDER).lower()
    model = os.getenv("EMBEDDING_MODEL", EMBEDDING_MODEL)
    
    try:
        if provider == "google":
            client = get_genai_client()
            if not client:
                logger.error("❌ Gemini client not available for embeddings")
                return []
            response = client.models.embed_content(model=model, contents=query)
            return response.embeddings[0].values if response.embeddings else []
            
        elif provider == "openai":
            from openai import AsyncOpenAI
            api_key = os.getenv("OPENAI_API_KEY") or OPENAI_API_KEY
            if not api_key:
                logger.error("❌ OPENAI_API_KEY not set")
                return []
            client = AsyncOpenAI(api_key=api_key)
            response = await client.embeddings.create(input=[query], model=model)
            return response.data[0].embedding
            
        else:
            logger.error(f"❌ Unsupported embedding provider: {provider}")
            return []
            
    except Exception as e:
        logger.error(f"❌ Embedding error ({provider}): {e}")
        return []

async def batch_generate_embeddings(texts: List[str]) -> List[List[float]]:
    """Helper for batch processing embeddings if supported by provider."""
    provider = os.getenv("EMBEDDING_PROVIDER", EMBEDDING_PROVIDER).lower()
    model = os.getenv("EMBEDDING_MODEL", EMBEDDING_MODEL)
    
    if not texts:
        return []

    try:
        if provider == "google":
            client = get_genai_client()
            if not client:
                return []
            response = client.models.embed_content(model=model, contents=texts)
            return [e.values for e in response.embeddings] if response.embeddings else []
            
        elif provider == "openai":
            from openai import AsyncOpenAI
            api_key = os.getenv("OPENAI_API_KEY") or OPENAI_API_KEY
            client = AsyncOpenAI(api_key=api_key)
            response = await client.embeddings.create(input=texts, model=model)
            return [d.embedding for d in response.data]
            
        else:
            # Sequential fallback for other providers
            return [await generate_embedding(t) for t in texts]
            
    except Exception as e:
        logger.error(f"❌ Batch embedding error ({provider}): {e}")
        return []
