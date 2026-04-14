import os
from typing import List, Optional, Dict
from shared.otel_logger import get_otel_logger
from shared.usage_tracking import text_payload_details, text_payload_stats, track_model_usage
# Configuration from environment variables with defaults
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_PROVIDER = "openai"
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "text-embedding-3-small")
EMBEDDING_OUTPUT_DIMENSIONALITY = int(os.getenv("EMBEDDING_OUTPUT_DIMENSIONALITY", "768"))

logger = get_otel_logger("embeddings", "shared")

_logged_embedding_configs = set()

def _log_embedding_config_once(*, action: str, provider: str, model: str, dimensionality: int, batch_size: Optional[int] = None) -> None:
    """
    Logs the active embedding configuration (no PII, no text content).
    De-dupes logs by (action, provider, model, dimensionality, batch_size).
    """
    try:
        key = (action, provider, model, dimensionality, batch_size)
        if key in _logged_embedding_configs:
            return
        _logged_embedding_configs.add(key)
        # Include the key config in the message because some prod log viewers only show the message,
        # not structured fields.
        logger.info(
            f"embedding config action={action} provider={provider} model={model} dimensions={dimensionality} batch_size={batch_size}",
            extra={
                "action": action,
                "provider": provider,
                "model": model,
                "dimensions": dimensionality,
                "batch_size": batch_size,
            },
        )
    except Exception:
        # Never fail an embedding call because of logging.
        return

def _openai_embedding_dimensions() -> Optional[int]:
    dimensionality = int(os.getenv("EMBEDDING_OUTPUT_DIMENSIONALITY", str(EMBEDDING_OUTPUT_DIMENSIONALITY)))
    return dimensionality if dimensionality > 0 else None


def _openai_usage_tokens(response, texts: List[str], model: str) -> tuple[int, int, str]:
    usage = getattr(response, "usage", None)
    prompt_tokens = int(getattr(usage, "prompt_tokens", 0) or 0) if usage else 0
    total_tokens = int(getattr(usage, "total_tokens", 0) or 0) if usage else 0
    if prompt_tokens:
        return prompt_tokens, total_tokens or prompt_tokens, "provider_usage"

    return 0, 0, "provider_usage_unavailable"


async def _track_openai_embedding_usage(
    *,
    response,
    texts: List[str],
    model: str,
    request_metadata: Optional[Dict],
) -> None:
    try:
        dimensionality = _openai_embedding_dimensions()
        prompt_tokens, total_tokens, token_source = _openai_usage_tokens(response, texts, model)
        usage_metadata = {
            "embedding_provider": "openai",
            "embedding_model": model,
            "batch_size": len(texts),
            "dimensions": dimensionality,
            "token_source": token_source,
            "sdk": "openai.embeddings.create",
            **text_payload_stats(texts),
            **text_payload_details(texts),
        }
        if request_metadata:
            usage_metadata.update(request_metadata)

        tracked = await track_model_usage(
            provider="openai",
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=0,
            total_tokens=total_tokens,
            api_call_type="embedding",
            request_metadata=usage_metadata,
        )
        if tracked:
            logger.info(
                "Tracked OpenAI embedding usage metadata "
                f"model={model} batch_size={len(texts)} "
                f"chars={usage_metadata.get('input_character_count')} "
                f"bytes={usage_metadata.get('input_size_bytes')} "
                f"text_chunks={len(usage_metadata.get('input_text_chunks') or [])}"
            )
        else:
            logger.warning(f"OpenAI embedding usage tracking returned false model={model} batch_size={len(texts)}")
    except Exception as usage_error:
        logger.warning(f"⚠️ Failed to track OpenAI embedding usage: {usage_error}")


async def _openai_embed(texts: List[str], request_metadata: Optional[Dict] = None) -> List[List[float]]:
    from openai import AsyncOpenAI

    model = os.getenv("EMBEDDING_MODEL", EMBEDDING_MODEL)
    dimensionality = _openai_embedding_dimensions()
    _log_embedding_config_once(
        action="embed_batch",
        provider="openai",
        model=model,
        dimensionality=dimensionality or 0,
        batch_size=len(texts),
    )

    api_key = os.getenv("OPENAI_API_KEY") or OPENAI_API_KEY
    if not api_key:
        logger.error("❌ OPENAI_API_KEY not set")
        return []

    client = AsyncOpenAI(api_key=api_key)
    kwargs = {"input": texts, "model": model}
    if dimensionality:
        kwargs["dimensions"] = dimensionality
    response = await client.embeddings.create(**kwargs)
    await _track_openai_embedding_usage(
        response=response,
        texts=texts,
        model=model,
        request_metadata=request_metadata,
    )
    return [d.embedding for d in response.data]

async def generate_embedding(query: str, request_metadata: Optional[Dict] = None) -> List[float]:
    """Generate an OpenAI embedding vector."""
    provider = EMBEDDING_PROVIDER
    model = os.getenv("EMBEDDING_MODEL", EMBEDDING_MODEL)
    dimensionality = _openai_embedding_dimensions() or 0
    _log_embedding_config_once(action="embed_query", provider=provider, model=model, dimensionality=dimensionality)
    
    try:
        embeddings = await _openai_embed([query], request_metadata)
        return embeddings[0] if embeddings else []
            
    except Exception as e:
        logger.error(f"❌ Embedding error ({provider}): {e}")
        return []

async def batch_generate_embeddings(texts: List[str], request_metadata: Optional[Dict] = None) -> List[List[float]]:
    """Batch-generate OpenAI embeddings."""
    provider = EMBEDDING_PROVIDER
    model = os.getenv("EMBEDDING_MODEL", EMBEDDING_MODEL)
    dimensionality = _openai_embedding_dimensions() or 0
    
    if not texts:
        return []

    try:
        _log_embedding_config_once(action="embed_batch", provider=provider, model=model, dimensionality=dimensionality, batch_size=len(texts))
        return await _openai_embed(texts, request_metadata)
            
    except Exception as e:
        logger.error(f"❌ Batch embedding error ({provider}): {e}")
        return []
