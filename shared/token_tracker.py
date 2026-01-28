"""
Token Usage Tracker
Tracks and accumulates token usage from Gemini API responses.
"""
import logging
import os
import sys
from pathlib import Path
from typing import Optional

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent))
from shared.db import railway_db, init_railway_db

logger = logging.getLogger(__name__)


async def get_db_connection():
    """Get database connection - use shared database utilities."""
    if railway_db is not None:
        return railway_db
    
    # Try to initialize if not available (fallback)
    database_url = os.getenv("DATABASE_URL") or os.getenv("RAILWAY_POSTGRES_URL")
    if database_url:
        try:
            db = await init_railway_db(database_url)
            return db
        except Exception as e:
            logger.error(f"❌ Failed to initialize database in token_tracker: {e}")
    
    return None






async def track_gemini_usage(prompt_tokens: int, candidates_tokens: int, session_id: str = None, message_id: str = None, api_call_type: str = 'rag', model: str = 'gemini-2.5-flash-lite'):
    """
    Track Gemini token usage and update llm_providers and token_usage_log tables.

    Args:
        prompt_tokens: Number of prompt tokens
        candidates_tokens: Number of candidate/output tokens
        session_id: UUID of the chat session (optional)
        message_id: UUID of the chat message (optional)
        api_call_type: Type of API call ('rag', 'search', etc.)
        model: Specific model used (default: gemini-2.5-flash-lite)
    """
    await track_gemini_usage_detailed(
        prompt_tokens=prompt_tokens,
        candidates_tokens=candidates_tokens,
        cache_read_tokens=0,
        cache_write_tokens=0,
        session_id=session_id,
        message_id=message_id,
        api_call_type=api_call_type,
        model=model
    )


async def track_gemini_usage_detailed(
    prompt_tokens: int,
    candidates_tokens: int,
    total_tokens: int = 0,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    session_id: str = None,
    message_id: str = None,
    api_call_type: str = 'rag',
    model: str = 'gemini-2.5-flash-lite'
):
    # Use provided total_tokens if available, otherwise calculate from components
    if total_tokens <= 0:
        total_tokens = prompt_tokens + candidates_tokens + cache_read_tokens + cache_write_tokens

    if total_tokens <= 0:
        return  # Skip if no tokens used

    try:
        logger.info("🔄 Starting token tracking for session: %s, message: %s, total_tokens: %s", session_id, message_id, total_tokens)
        db = await get_db_connection()
        if db and hasattr(db, '_pool') and db._pool is not None:
            logger.info("✅ Database connection available for token tracking")
            from shared.services.token_service import token_service
            await token_service.update_llm_provider_tokens(provider, model, prompt_tokens, completion_tokens, total_tokens)
            
            # Log detailed usage
            if session_id or message_id:
                usage_data = {
                    "session_id": session_id,
                    "message_id": message_id,
                    "provider": provider,
                    "model": model,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": candidates_tokens,
                    "total_tokens": total_tokens,
                    "cache_read_tokens": cache_read_tokens,
                    "cache_write_tokens": cache_write_tokens,
                    "api_call_type": api_call_type
                }
                await token_service.log_token_usage(**usage_data)
                logger.info("✅ Token usage logged successfully")
            else:
                logger.warning("⚠️ Skipping token_usage_log insert: neither session_id nor message_id provided")

            logger.info(f"✅ Tracked {provider} detailed usage: {total_tokens} tokens total used, session: {session_id}")
        else:
            logger.warning("Database not available for token tracking")
    except Exception as e:
        logger.error(f"Error tracking Gemini detailed token usage: {e}", exc_info=True)


async def track_gemini_usage_from_response(usage_obj, session_id: str = None, message_id: str = None, api_call_type: str = 'rag', model: str = 'gemini-2.5-flash-lite'):
    """
    Track Gemini token usage from API response usage object.
    """
    logger.info(f"🔍 Token tracking called for Gemini - session: {session_id}, message: {message_id}, type: {api_call_type}, model: {model}")

    if not usage_obj:
        logger.warning("⚠️ Gemini usage object is None or empty")
        return

    try:
        # Extract detailed token breakdown from Gemini usage_metadata object
        prompt_tokens = (
            getattr(usage_obj, 'promptTokenCount', 0) or
            getattr(usage_obj, 'prompt_token_count', 0) or
            getattr(usage_obj, 'input_tokens', 0) or
            getattr(usage_obj, 'prompt_tokens', 0) or
            0
        )

        candidates_tokens = (
            getattr(usage_obj, 'candidatesTokenCount', 0) or
            getattr(usage_obj, 'candidates_token_count', 0) or
            getattr(usage_obj, 'output_tokens', 0) or
            getattr(usage_obj, 'completion_tokens', 0) or
            0
        )

        total_tokens = (
            getattr(usage_obj, 'totalTokenCount', 0) or
            getattr(usage_obj, 'total_token_count', 0) or
            getattr(usage_obj, 'total_tokens', 0) or
            (prompt_tokens + candidates_tokens)
        )

        cache_read_tokens = getattr(usage_obj, 'cache_read_tokens', 0) or 0
        cache_write_tokens = getattr(usage_obj, 'cache_write_tokens', 0) or 0

        if total_tokens > 0 or prompt_tokens > 0:
            await track_gemini_usage_detailed(
                prompt_tokens=prompt_tokens,
                candidates_tokens=candidates_tokens,
                total_tokens=total_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
                session_id=session_id,
                message_id=message_id,
                api_call_type=api_call_type,
                model=model
            )
    except Exception as e:
        logger.error(f"❌ Error extracting Gemini usage from response: {e}", exc_info=True)


async def track_gemini_usage_with_db(run_usage, session_id: str = None, message_id: str = None, api_call_type: str = 'rag', model: str = 'gemini-2.5-flash-lite', db_connection=None):
    """
    Track Gemini token usage using an existing database connection.
    """
    try:
        # Extract token counts from RunUsage object
        prompt_tokens = getattr(run_usage, 'input_tokens', 0)
        candidates_tokens = getattr(run_usage, 'output_tokens', 0)
        cache_read_tokens = getattr(run_usage, 'details', {}).get('accepted_prediction_tokens', 0)
        cache_write_tokens = getattr(run_usage, 'details', {}).get('rejected_prediction_tokens', 0)

        if prompt_tokens <= 0 and candidates_tokens <= 0:
            return

        total_tokens = prompt_tokens + candidates_tokens + (cache_read_tokens or 0) + (cache_write_tokens or 0)

        if db_connection:
            from shared.services.token_service import token_service
            
            # Update llm_providers table
            await token_service.update_llm_provider_tokens('gemini', model, prompt_tokens, candidates_tokens, total_tokens)

            # Log detailed usage
            if session_id or message_id:
                usage_data = {
                    "session_id": session_id,
                    "message_id": message_id,
                    "provider": 'gemini',
                    "model": model,
                    "prompt_tokens": prompt_tokens,
                    "completion_tokens": candidates_tokens,
                    "total_tokens": total_tokens,
                    "cache_read_tokens": cache_read_tokens,
                    "cache_write_tokens": cache_write_tokens,
                    "api_call_type": api_call_type
                }
                await token_service.log_token_usage(**usage_data)

                logger.info(f"✅ Tracked Gemini usage with provided DB: {total_tokens} tokens total used, session: {session_id}")
    except Exception as e:
        logger.error(f"❌ Error tracking Gemini usage with provided DB: {e}", exc_info=True)

