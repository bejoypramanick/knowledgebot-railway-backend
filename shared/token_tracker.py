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
    """Get database connection, initializing if needed."""
    if railway_db is not None and hasattr(railway_db, '_pool') and railway_db._pool is not None:
        return railway_db
    
    # Initialize database if not already initialized
    database_url = os.getenv("DATABASE_URL") or os.getenv("RAILWAY_POSTGRES_URL") or os.getenv("POSTGRES_URL")
    if database_url:
        await init_railway_db(database_url)
        return railway_db
    
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
    """
    Track detailed Gemini token usage with cache token breakdown.

    Args:
        prompt_tokens: Number of prompt tokens
        candidates_tokens: Number of candidate/output tokens
        cache_read_tokens: Tokens read from cache
        cache_write_tokens: Tokens written to cache
        session_id: UUID of the chat session (optional)
        message_id: UUID of the chat message (optional)
        api_call_type: Type of API call ('rag', 'search', etc.)
        model: Specific model used (default: gemini-2.5-flash-lite)
    """
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
            async with db.acquire() as conn:
                # First, update llm_providers table
                await conn.execute(
                    """
                    INSERT INTO llm_providers (provider_name, token_used, token_limit, is_active)
                    VALUES ('gemini', $1, 20000, true)
                    ON CONFLICT (provider_name) DO UPDATE
                    SET token_used = COALESCE(llm_providers.token_used, 0) + $1,
                        token_limit = COALESCE(llm_providers.token_limit, 20000),
                        is_active = true
                    """,
                    total_tokens
                )

                # Get current usage from llm_providers for calculation
                current_usage = await conn.fetchval(
                    "SELECT COALESCE(token_used, 0) FROM llm_providers WHERE provider_name = 'gemini'"
                ) or 0

                limit_value = 20000
                available = limit_value - current_usage

                # Log detailed usage in token_usage_log table
                logger.info(f"🔍 Checking session_id/message_id for insert: session_id={session_id}, message_id={message_id}")
                if session_id or message_id:
                    log_query = """
                        INSERT INTO token_usage_log (
                            session_id, message_id, provider, model, prompt_tokens, completion_tokens,
                            total_tokens, cache_read_tokens, cache_write_tokens, api_call_type, created_at
                        )
                        VALUES ($1, $2, 'gemini', $3, $4, $5, $6, $7, $8, $9, NOW())
                        """
                    logger.info(f"🔍 Executing INSERT on token_usage_log (track_gemini_usage_detailed): {log_query.strip()} | Params: [{session_id}, {message_id}, 'gemini', '{model}', {prompt_tokens}, {candidates_tokens}, {total_tokens}, {cache_read_tokens}, {cache_write_tokens}, '{api_call_type}']")
                    await conn.execute(log_query,
                        session_id, message_id, model, prompt_tokens, candidates_tokens, total_tokens,
                        cache_read_tokens, cache_write_tokens, api_call_type
                    )
                    logger.info("✅ Database INSERT executed successfully")
                else:
                    logger.warning("⚠️ Skipping token_usage_log insert: neither session_id nor message_id provided")

                logger.info(f"✅ Tracked Gemini detailed usage: {total_tokens} tokens (prompt: {prompt_tokens}, candidates: {candidates_tokens}, cache_read: {cache_read_tokens}, cache_write: {cache_write_tokens}), total used: {current_usage}, session: {session_id}")
        else:
            logger.warning("Database not available for token tracking")
    except Exception as e:
        logger.error(f"Error tracking Gemini detailed token usage: {e}", exc_info=True)




async def track_gemini_usage_from_response(usage_obj, session_id: str = None, message_id: str = None, api_call_type: str = 'rag', model: str = 'gemini-2.5-flash-lite'):
    """
    Track Gemini token usage from API response usage object.

    Args:
        usage_obj: Gemini usage object with detailed token breakdown
        session_id: UUID of the chat session (optional)
        message_id: UUID of the chat message (optional)
        api_call_type: Type of API call ('rag', 'search', etc.)
        model: Specific model used (default: gemini-2.5-flash-lite)
    """
    logger.info(f"🔍 Token tracking called for Gemini - session: {session_id}, message: {message_id}, type: {api_call_type}, model: {model}")
    logger.debug(f"🔍 Usage object type: {type(usage_obj)}, value: {usage_obj}")

    if not usage_obj:
        logger.warning("⚠️ Gemini usage object is None or empty")
        return

    try:
        # Extract detailed token breakdown from Gemini usage_metadata object
        # Gemini API uses camelCase field names, try both camelCase and snake_case
        prompt_tokens = (
            getattr(usage_obj, 'promptTokenCount', 0) or  # camelCase (Gemini API)
            getattr(usage_obj, 'prompt_token_count', 0) or # snake_case
            getattr(usage_obj, 'input_tokens', 0) or       # pydantic-ai format
            getattr(usage_obj, 'prompt_tokens', 0) or      # OpenAI format
            0
        )

        candidates_tokens = (
            getattr(usage_obj, 'candidatesTokenCount', 0) or # camelCase (Gemini API)
            getattr(usage_obj, 'candidates_token_count', 0) or # snake_case
            getattr(usage_obj, 'output_tokens', 0) or         # pydantic-ai format
            getattr(usage_obj, 'completion_tokens', 0) or     # OpenAI format
            0
        )

        total_tokens = (
            getattr(usage_obj, 'totalTokenCount', 0) or     # camelCase (Gemini API)
            getattr(usage_obj, 'total_token_count', 0) or   # snake_case
            getattr(usage_obj, 'total_tokens', 0) or        # pydantic-ai format
            (prompt_tokens + candidates_tokens)             # fallback calculation
        )

        cache_read_tokens = getattr(usage_obj, 'cache_read_tokens', 0) or 0
        cache_write_tokens = getattr(usage_obj, 'cache_write_tokens', 0) or 0

    logger.info(f"📊 Gemini usage extracted - prompt: {prompt_tokens}, candidates: {candidates_tokens}, total: {total_tokens}")
    logger.info(f"📊 Full usage object: {usage_obj}")
    logger.info(f"📊 Usage object type: {type(usage_obj)}")
    logger.info(f"📊 Usage object attributes: {dir(usage_obj) if hasattr(usage_obj, '__dict__') else 'No __dict__'}")

        if prompt_tokens > 0 or candidates_tokens > 0 or total_tokens > 0 or cache_read_tokens > 0 or cache_write_tokens > 0:
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
            logger.info("✅ Gemini detailed token tracking completed successfully")
        else:
            logger.warning("⚠️ No token usage to track (zero tokens)")
    except Exception as e:
        logger.error(f"❌ Error extracting Gemini usage from response: {e}", exc_info=True)




async def track_gemini_usage_with_db(run_usage, session_id: str = None, message_id: str = None, api_call_type: str = 'rag', model: str = 'gemini-2.5-flash-lite', db_connection=None):
    """
    Track Gemini token usage using an existing database connection.
    This version accepts a database connection parameter instead of getting its own.

    Args:
        run_usage: Pydantic-ai RunUsage object
        session_id: UUID of the chat session (optional)
        message_id: UUID of the chat message (optional)
        api_call_type: Type of API call ('chat', 'sentiment', 'summary', etc.)
        model: Specific model used
        db_connection: Existing database connection to use
    """
    try:
        # Extract token counts from RunUsage object for Gemini
        prompt_tokens = getattr(run_usage, 'input_tokens', 0)
        candidates_tokens = getattr(run_usage, 'output_tokens', 0)
        cache_read_tokens = getattr(run_usage, 'details', {}).get('accepted_prediction_tokens', 0)
        cache_write_tokens = getattr(run_usage, 'details', {}).get('rejected_prediction_tokens', 0)

        if prompt_tokens <= 0 and candidates_tokens <= 0 and cache_read_tokens <= 0 and cache_write_tokens <= 0:
            logger.warning("⚠️ No token usage to track (zero tokens)")
            return

        total_tokens = prompt_tokens + candidates_tokens + cache_read_tokens + cache_write_tokens

        # Use the provided database connection
        if db_connection:
            async with db_connection.acquire() as conn:
                # First, update llm_providers table
                await conn.execute(
                    """
                    INSERT INTO llm_providers (provider_name, token_used, token_limit, is_active)
                    VALUES ('gemini', $1, 20000, true)
                    ON CONFLICT (provider_name) DO UPDATE
                    SET token_used = COALESCE(llm_providers.token_used, 0) + $1,
                        token_limit = COALESCE(llm_providers.token_limit, 20000),
                        is_active = true
                    """,
                    total_tokens
                )

                # Get current usage from llm_providers for calculation
                current_usage = await conn.fetchval(
                    "SELECT COALESCE(token_used, 0) FROM llm_providers WHERE provider_name = 'gemini'"
                ) or 0

                limit_value = 20000
                available = limit_value - current_usage

                # Log detailed usage in token_usage_log table
                logger.info(f"🔍 Checking session_id/message_id for insert: session_id={session_id}, message_id={message_id}")
                if session_id or message_id:
                    log_query = """
                        INSERT INTO token_usage_log (
                            session_id, message_id, provider, model, prompt_tokens, completion_tokens,
                            total_tokens, cache_read_tokens, cache_write_tokens, api_call_type, created_at
                        )
                        VALUES ($1, $2, 'gemini', $3, $4, $5, $6, $7, $8, $9, NOW())
                        """
                    logger.info(f"🔍 Executing INSERT on token_usage_log (track_gemini_usage_with_db): {log_query.strip()} | Params: [{session_id}, {message_id}, 'gemini', '{model}', {prompt_tokens}, {candidates_tokens}, {total_tokens}, {cache_read_tokens}, {cache_write_tokens}, '{api_call_type}']")
                    await conn.execute(log_query,
                        session_id, message_id, model, prompt_tokens, candidates_tokens, total_tokens,
                        cache_read_tokens, cache_write_tokens, api_call_type
                    )

                logger.info(f"✅ Tracked Gemini detailed usage with provided DB: {total_tokens} tokens (prompt: {prompt_tokens}, candidates: {candidates_tokens}, cache_read: {cache_read_tokens}, cache_write: {cache_write_tokens}), total used: {current_usage}, session: {session_id}")
        else:
            logger.warning("No database connection provided for token tracking")
    except Exception as e:
        logger.error(f"❌ Error tracking Gemini detailed token usage with provided DB: {e}", exc_info=True)

