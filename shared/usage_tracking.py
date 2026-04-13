"""
Shared usage tracking for non-chat model calls.

Chat agent calls use chatbot_orchestration.core.token_tracker because they have
session/message context. Shared services such as embeddings and vision OCR may
run from workers without a chat session, so this module writes directly to the
same token_usage_log table with nullable session/message IDs.
"""

import json
import os
from typing import Any, Dict, Optional

from sqlalchemy import text

from shared.otel_logger import get_otel_logger
from shared.sqlalchemy_db import get_db_session

logger = get_otel_logger("usage_tracking", "shared")


def estimate_text_tokens(value: Any) -> int:
    """Estimate tokens locally without adding a second provider API call."""
    if value is None:
        return 0
    if isinstance(value, list):
        return sum(estimate_text_tokens(item) for item in value)
    text_value = str(value)
    if not text_value.strip():
        return 0
    try:
        from litellm import token_counter

        return int(token_counter(text=text_value) or 0)
    except Exception:
        return max(1, len(text_value) // 4)


def text_payload_stats(value: Any) -> Dict[str, Any]:
    """Return character and UTF-8 byte size for text payloads."""
    if value is None:
        text_value = ""
        item_count = 0
    elif isinstance(value, list):
        text_parts = ["" if item is None else str(item) for item in value]
        text_value = "\n".join(text_parts)
        item_count = len(value)
    else:
        text_value = str(value)
        item_count = 1

    size_bytes = len(text_value.encode("utf-8"))
    stats: Dict[str, Any] = {
        "input_character_count": len(text_value),
        "input_size_bytes": size_bytes,
        "input_size_kb": round(size_bytes / 1024, 3),
        "input_size_mb": round(size_bytes / (1024 * 1024), 6),
    }
    if item_count:
        stats["input_item_count"] = item_count
    return stats


def text_payload_details(value: Any, *, max_chars: Optional[int] = None) -> Dict[str, Any]:
    """Return the actual text payload, capped to keep usage rows bounded."""
    if max_chars is None:
        max_chars = int(os.getenv("USAGE_TRACKING_MAX_TEXT_CHARS", "20000"))

    if value is None:
        parts = []
    elif isinstance(value, list):
        parts = ["" if item is None else str(item) for item in value]
    else:
        parts = [str(value)]

    remaining = max(0, max_chars)
    captured = []
    truncated = False
    for part in parts:
        if remaining <= 0:
            truncated = truncated or bool(part)
            captured.append("")
            continue
        if len(part) > remaining:
            captured.append(part[:remaining])
            truncated = True
            remaining = 0
        else:
            captured.append(part)
            remaining -= len(part)

    return {
        "input_text_capture": "enabled",
        "input_text_chunks": captured,
        "input_text_truncated": truncated,
        "input_text_capture_limit_chars": max_chars,
    }


def binary_payload_stats(value: bytes, *, prefix: str = "input") -> Dict[str, Any]:
    """Return byte size for binary payloads such as images."""
    size_bytes = len(value or b"")
    return {
        f"{prefix}_size_bytes": size_bytes,
        f"{prefix}_size_kb": round(size_bytes / 1024, 3),
        f"{prefix}_size_mb": round(size_bytes / (1024 * 1024), 6),
    }


def gemini_pricing_for_call(
    *, model: str, api_call_type: str
) -> Dict[str, float]:
    """Return paid-tier USD per 1M token rates for tracked Gemini calls."""
    normalized_model = (model or "").lower()
    normalized_call = (api_call_type or "").lower()

    if "embedding" in normalized_model or "embedding" in normalized_call:
        return {
            "standard_input": 0.15,
            "completion": 0.0,
            "cache_read": 0.0,
            "cache_write": 0.0,
        }

    if "1.5-flash" in normalized_model:
        return {
            "standard_input": 0.075,
            "completion": 0.30,
            "cache_read": 0.01875,
            "cache_write": 0.0,
        }

    return {
        "standard_input": 0.10,
        "completion": 0.40,
        "cache_read": 0.01,
        "cache_write": 0.10,
    }


async def track_model_usage(
    *,
    provider: str,
    model: str,
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: Optional[int] = None,
    api_call_type: str,
    request_metadata: Optional[Dict[str, Any]] = None,
    session_id: Optional[str] = None,
    message_id: Optional[str] = None,
) -> bool:
    """Persist one provider call in token_usage_log."""
    prompt_tokens = int(prompt_tokens or 0)
    completion_tokens = int(completion_tokens or 0)
    if total_tokens is None:
        total_tokens = prompt_tokens + completion_tokens
    total_tokens = int(total_tokens or 0)

    metadata = dict(request_metadata or {})
    cache_read = int(metadata.get("cache_read_tokens") or 0)
    cache_write = int(metadata.get("cache_write_tokens") or 0)

    pricing = metadata.get("pricing_usd_per_1m") or {}
    if not pricing and provider == "gemini":
        pricing = gemini_pricing_for_call(model=model, api_call_type=api_call_type)

    standard_input = max(0, prompt_tokens - cache_read)
    input_rate = float(pricing.get("standard_input", 0.0) or 0.0)
    output_rate = float(pricing.get("completion", 0.0) or 0.0)
    cache_read_rate = float(pricing.get("cache_read", 0.0) or 0.0)
    cache_write_rate = float(pricing.get("cache_write", 0.0) or 0.0)
    cost_usd = (
        (standard_input * input_rate)
        + (completion_tokens * output_rate)
        + (cache_read * cache_read_rate)
        + (cache_write * cache_write_rate)
    ) / 1_000_000.0

    metadata.update(
        {
            "cost_usd": cost_usd,
            "standard_input_tokens": standard_input,
            "pricing_usd_per_1m": pricing,
            "usage_capture": "shared.usage_tracking",
        }
    )

    query = """
        INSERT INTO token_usage_log (
            session_id, message_id, provider, model, prompt_tokens,
            completion_tokens, total_tokens, cost_cents, api_call_type, request_metadata
        ) VALUES (
            CAST(:session_id AS UUID), CAST(:message_id AS UUID), :provider, :model,
            :prompt_tokens, :completion_tokens, :total_tokens, :cost_cents,
            :api_call_type, :request_metadata
        )
    """
    params = {
        "session_id": session_id,
        "message_id": message_id,
        "provider": provider,
        "model": model,
        "prompt_tokens": prompt_tokens,
        "completion_tokens": completion_tokens,
        "total_tokens": total_tokens,
        "cost_cents": round(cost_usd * 100.0),
        "api_call_type": api_call_type,
        "request_metadata": json.dumps(metadata),
    }

    try:
        async with get_db_session() as db:
            await db.execute(text(query), params)
            await db.execute(
                text("""
                    MERGE INTO llm_providers AS target
                    USING (VALUES (CAST(:provider AS VARCHAR), CAST(:total_tokens AS BIGINT), CAST(:default_limit AS BIGINT)))
                          AS source(provider_name, token_used, token_limit)
                    ON target.provider_name = source.provider_name
                    WHEN MATCHED THEN
                        UPDATE SET token_used = target.token_used + source.token_used, updated_at = NOW()
                    WHEN NOT MATCHED THEN
                        INSERT (provider_name, token_used, token_limit, is_active)
                        VALUES (source.provider_name, source.token_used, source.token_limit, true)
                """),
                {
                    "provider": provider,
                    "total_tokens": total_tokens,
                    "default_limit": 20000,
                },
            )
            await db.commit()
        return True
    except Exception as exc:
        logger.warning(
            f"Failed to track model usage provider={provider} model={model} call={api_call_type}: {exc}"
        )
        return False
