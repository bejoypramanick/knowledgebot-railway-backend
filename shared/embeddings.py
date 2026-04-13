import os
import asyncio
from typing import List, Optional
from shared.otel_logger import get_otel_logger
from shared.usage_tracking import estimate_text_tokens, text_payload_details, text_payload_stats, track_model_usage
# Configuration from environment variables with defaults
GEMINI_API_KEY = os.getenv("GEMINI_API_KEY")
OPENAI_API_KEY = os.getenv("OPENAI_API_KEY")
EMBEDDING_PROVIDER = os.getenv("EMBEDDING_PROVIDER", "google").lower()
EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "gemini-embedding-001")
EMBEDDING_OUTPUT_DIMENSIONALITY = int(os.getenv("EMBEDDING_OUTPUT_DIMENSIONALITY", "768"))

logger = get_otel_logger("embeddings", "shared")

# Lazy clients
_genai_client = None

_LEGACY_GOOGLE_EMBEDDING_FALLBACKS = {
    "text-embedding-004": "gemini-embedding-001",
}
_GOOGLE_BATCH_EMBED_LIMIT = 100

USE_LITELLM_EMBEDDINGS = os.getenv("USE_LITELLM_EMBEDDINGS", "true").lower() == "true"

_logged_embedding_configs = set()

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


def _google_embed_config():
    from google.genai import types

    dimensionality = int(os.getenv("EMBEDDING_OUTPUT_DIMENSIONALITY", str(EMBEDDING_OUTPUT_DIMENSIONALITY)))
    if dimensionality <= 0:
        return None
    return types.EmbedContentConfig(output_dimensionality=dimensionality)

def _litellm_embedding_model(provider: str, model: str) -> str:
    # LiteLLM uses provider/model for some backends (Gemini in particular).
    if not model:
        return model
    if "/" in model:
        return model
    if provider == "google":
        return f"gemini/{model}"
    return model

def _log_embedding_config_once(*, action: str, provider: str, model: str, dimensionality: int, batch_size: Optional[int] = None) -> None:
    """
    Logs the active embedding configuration (no PII, no text content).
    De-dupes logs by (action, provider, model, dimensionality, batch_size).
    """
    try:
        litellm_model = _litellm_embedding_model(provider, model) if USE_LITELLM_EMBEDDINGS else None
        key = (action, provider, model, dimensionality, batch_size, bool(USE_LITELLM_EMBEDDINGS), litellm_model)
        if key in _logged_embedding_configs:
            return
        _logged_embedding_configs.add(key)
        # Include the key config in the message because some prod log viewers only show the message,
        # not structured fields.
        logger.info(
            f"embedding config action={action} provider={provider} model={model} dimensions={dimensionality} use_litellm={bool(USE_LITELLM_EMBEDDINGS)} litellm_model={litellm_model} batch_size={batch_size}",
            extra={
                "action": action,
                "provider": provider,
                "model": model,
                "dimensions": dimensionality,
                "use_litellm": bool(USE_LITELLM_EMBEDDINGS),
                "litellm_model": litellm_model,
                "batch_size": batch_size,
            },
        )
    except Exception:
        # Never fail an embedding call because of logging.
        return

async def _litellm_embed(texts: List[str], provider: str, model: str) -> List[List[float]]:
    import asyncio as _asyncio
    from litellm import embedding

    dimensionality = int(os.getenv("EMBEDDING_OUTPUT_DIMENSIONALITY", str(EMBEDDING_OUTPUT_DIMENSIONALITY)))
    _log_embedding_config_once(action="embed_batch", provider=provider, model=model, dimensionality=dimensionality, batch_size=len(texts))
    litellm_model = _litellm_embedding_model(provider, model)

    def _call():
        # `dimensions` is supported for many providers/models; if unsupported, LiteLLM will raise.
        return embedding(model=litellm_model, input=texts, dimensions=dimensionality)

    resp = await _asyncio.to_thread(_call)
    try:
        usage = resp.get("usage") if isinstance(resp, dict) else getattr(resp, "usage", None)
        prompt_tokens = 0
        total_tokens = 0
        if usage:
            prompt_tokens = (
                (usage.get("prompt_tokens") if isinstance(usage, dict) else getattr(usage, "prompt_tokens", 0))
                or (usage.get("input_tokens") if isinstance(usage, dict) else getattr(usage, "input_tokens", 0))
                or 0
            )
            total_tokens = (
                (usage.get("total_tokens") if isinstance(usage, dict) else getattr(usage, "total_tokens", 0))
                or prompt_tokens
            )
        if not prompt_tokens:
            prompt_tokens = estimate_text_tokens(texts)
            total_tokens = prompt_tokens
        usage_metadata = {
            "embedding_provider": provider,
            "embedding_model": model,
            "litellm_model": litellm_model,
            "batch_size": len(texts),
            "dimensions": dimensionality,
            "token_source": "provider_usage" if usage else "estimated_text_tokens",
            **text_payload_stats(texts),
            **text_payload_details(texts),
        }
        tracked = await track_model_usage(
            provider="gemini" if provider == "google" else provider,
            model=model,
            prompt_tokens=prompt_tokens,
            completion_tokens=0,
            total_tokens=total_tokens,
            api_call_type="embedding",
            request_metadata=usage_metadata,
        )
        if tracked:
            logger.info(
                "Tracked LiteLLM embedding usage metadata "
                f"provider={provider} model={model} batch_size={len(texts)} "
                f"chars={usage_metadata.get('input_character_count')} "
                f"bytes={usage_metadata.get('input_size_bytes')} "
                f"text_chunks={len(usage_metadata.get('input_text_chunks') or [])}"
            )
        else:
            logger.warning(
                "LiteLLM embedding usage tracking returned false "
                f"provider={provider} model={model} batch_size={len(texts)}"
            )
    except Exception as usage_error:
        logger.warning(f"⚠️ Failed to track LiteLLM embedding usage: {usage_error}")
    data = resp.get("data") if isinstance(resp, dict) else getattr(resp, "data", None)
    if not data:
        return []
    out: List[List[float]] = []
    for item in data:
        if isinstance(item, dict):
            out.append(item.get("embedding") or [])
        else:
            out.append(getattr(item, "embedding", []) or [])
    return out


def _google_embedding_model_candidates(model: str) -> List[str]:
    candidates = [model]
    fallback = _LEGACY_GOOGLE_EMBEDDING_FALLBACKS.get(model)
    if fallback and fallback not in candidates:
        candidates.append(fallback)
    return candidates


def _is_google_model_not_found_error(exc: Exception) -> bool:
    error_text = str(exc)
    return "404" in error_text or "NOT_FOUND" in error_text

async def generate_embedding(query: str) -> List[float]:
    """Generate an embedding vector using the configured provider."""
    provider = os.getenv("EMBEDDING_PROVIDER", EMBEDDING_PROVIDER).lower()
    model = os.getenv("EMBEDDING_MODEL", EMBEDDING_MODEL)
    dimensionality = int(os.getenv("EMBEDDING_OUTPUT_DIMENSIONALITY", str(EMBEDDING_OUTPUT_DIMENSIONALITY)))
    _log_embedding_config_once(action="embed_query", provider=provider, model=model, dimensionality=dimensionality)
    
    try:
        if USE_LITELLM_EMBEDDINGS:
            embeddings = await _litellm_embed([query], provider, model)
            return embeddings[0] if embeddings else []

        if provider == "google":
            client = get_genai_client()
            if not client:
                logger.error("❌ Gemini client not available for embeddings")
                return []
            last_error = None
            for candidate_model in _google_embedding_model_candidates(model):
                try:
                    response = client.models.embed_content(
                        model=candidate_model,
                        contents=query,
                        config=_google_embed_config(),
                    )
                    await track_model_usage(
                        provider="gemini",
                        model=candidate_model,
                        prompt_tokens=estimate_text_tokens(query),
                        completion_tokens=0,
                        api_call_type="embedding",
                        request_metadata={
                            "embedding_provider": provider,
                            "embedding_model": candidate_model,
                            "batch_size": 1,
                            "dimensions": dimensionality,
                            "token_source": "estimated_text_tokens",
                            "sdk": "google.genai.embed_content",
                            **text_payload_stats(query),
                            **text_payload_details(query),
                        },
                    )
                    return response.embeddings[0].values if response.embeddings else []
                except Exception as e:
                    last_error = e
                    if _is_google_model_not_found_error(e) and candidate_model != _google_embedding_model_candidates(model)[-1]:
                        logger.warning(f"⚠️ Google embedding model '{candidate_model}' not found. Retrying with fallback model.")
                        continue
                    raise last_error
            
        elif provider == "openai":
            from openai import AsyncOpenAI
            api_key = os.getenv("OPENAI_API_KEY") or OPENAI_API_KEY
            if not api_key:
                logger.error("❌ OPENAI_API_KEY not set")
                return []
            client = AsyncOpenAI(api_key=api_key)
            response = await client.embeddings.create(input=[query], model=model)
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else estimate_text_tokens(query)
            total_tokens = getattr(usage, "total_tokens", prompt_tokens) if usage else prompt_tokens
            await track_model_usage(
                provider="openai",
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=0,
                total_tokens=total_tokens,
                api_call_type="embedding",
                request_metadata={
                    "embedding_provider": provider,
                    "embedding_model": model,
                    "batch_size": 1,
                    "dimensions": dimensionality,
                    "token_source": "provider_usage" if usage else "estimated_text_tokens",
                    **text_payload_stats(query),
                    **text_payload_details(query),
                },
            )
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
    dimensionality = int(os.getenv("EMBEDDING_OUTPUT_DIMENSIONALITY", str(EMBEDDING_OUTPUT_DIMENSIONALITY)))
    
    if not texts:
        return []

    try:
        _log_embedding_config_once(action="embed_batch", provider=provider, model=model, dimensionality=dimensionality, batch_size=len(texts))
        if USE_LITELLM_EMBEDDINGS:
            # Keep batch limit behavior consistent for Google/Gemini.
            if provider == "google":
                all_embeddings: List[List[float]] = []
                for i in range(0, len(texts), _GOOGLE_BATCH_EMBED_LIMIT):
                    batch = texts[i:i + _GOOGLE_BATCH_EMBED_LIMIT]
                    all_embeddings.extend(await _litellm_embed(batch, provider, model))
                return all_embeddings
            return await _litellm_embed(texts, provider, model)

        if provider == "google":
            client = get_genai_client()
            if not client:
                return []
            last_error = None
            for candidate_model in _google_embedding_model_candidates(model):
                try:
                    all_embeddings: List[List[float]] = []
                    for i in range(0, len(texts), _GOOGLE_BATCH_EMBED_LIMIT):
                        batch = texts[i:i + _GOOGLE_BATCH_EMBED_LIMIT]
                        response = client.models.embed_content(
                            model=candidate_model,
                            contents=batch,
                            config=_google_embed_config(),
                        )
                        await track_model_usage(
                            provider="gemini",
                            model=candidate_model,
                            prompt_tokens=estimate_text_tokens(batch),
                            completion_tokens=0,
                            api_call_type="embedding",
                            request_metadata={
                                "embedding_provider": provider,
                                "embedding_model": candidate_model,
                                "batch_size": len(batch),
                                "dimensions": dimensionality,
                                "token_source": "estimated_text_tokens",
                                "sdk": "google.genai.embed_content",
                                **text_payload_stats(batch),
                                **text_payload_details(batch),
                            },
                        )
                        batch_embeddings = [e.values for e in response.embeddings] if response.embeddings else []
                        all_embeddings.extend(batch_embeddings)
                    return all_embeddings
                except Exception as e:
                    last_error = e
                    if _is_google_model_not_found_error(e) and candidate_model != _google_embedding_model_candidates(model)[-1]:
                        logger.warning(f"⚠️ Google embedding model '{candidate_model}' not found. Retrying with fallback model.")
                        continue
                    raise last_error
            
        elif provider == "openai":
            from openai import AsyncOpenAI
            api_key = os.getenv("OPENAI_API_KEY") or OPENAI_API_KEY
            client = AsyncOpenAI(api_key=api_key)
            response = await client.embeddings.create(input=texts, model=model)
            usage = getattr(response, "usage", None)
            prompt_tokens = getattr(usage, "prompt_tokens", 0) if usage else estimate_text_tokens(texts)
            total_tokens = getattr(usage, "total_tokens", prompt_tokens) if usage else prompt_tokens
            await track_model_usage(
                provider="openai",
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=0,
                total_tokens=total_tokens,
                api_call_type="embedding",
                request_metadata={
                    "embedding_provider": provider,
                    "embedding_model": model,
                    "batch_size": len(texts),
                    "dimensions": dimensionality,
                    "token_source": "provider_usage" if usage else "estimated_text_tokens",
                    **text_payload_stats(texts),
                    **text_payload_details(texts),
                },
            )
            return [d.embedding for d in response.data]
            
        else:
            # Sequential fallback for other providers
            return [await generate_embedding(t) for t in texts]
            
    except Exception as e:
        logger.error(f"❌ Batch embedding error ({provider}): {e}")
        return []
