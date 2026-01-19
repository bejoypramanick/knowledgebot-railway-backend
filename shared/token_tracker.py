"""
Token Usage Tracker
Tracks and accumulates token usage from OpenAI and Gemini API responses.
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


async def track_openai_usage(input_tokens: int, output_tokens: int, session_id: str = None, message_id: str = None, api_call_type: str = 'chat', model: str = None):
    """
    Track OpenAI token usage and update both llm_providers, token_usage_cache, and token_usage_log tables.

    Args:
        input_tokens: Number of input/prompt tokens
        output_tokens: Number of output/completion tokens
        session_id: UUID of the chat session (optional)
        message_id: UUID of the chat message (optional)
        api_call_type: Type of API call ('chat', 'sentiment', 'summary', etc.)
        model: Specific model used (optional)
    """
    if input_tokens <= 0 and output_tokens <= 0:
        return  # Skip if no tokens used

    total_tokens = input_tokens + output_tokens

    try:
        db = await get_db_connection()
        if db and hasattr(db, '_pool') and db._pool is not None:
            async with db.acquire() as conn:
                # First, update llm_providers table
                await conn.execute(
                    """
                    INSERT INTO llm_providers (provider_name, token_used, token_limit, is_active)
                    VALUES ('deepseek', $1, 150000, true)
                    ON CONFLICT (provider_name) DO UPDATE
                    SET token_used = COALESCE(llm_providers.token_used, 0) + $1,
                        token_limit = COALESCE(llm_providers.token_limit, 150000),
                        is_active = true
                    """,
                    total_tokens
                )

                # Get current usage from llm_providers for calculation
                current_usage = await conn.fetchval(
                    "SELECT COALESCE(token_used, 0) FROM llm_providers WHERE provider_name = 'deepseek'"
                ) or 0

                limit_value = 150000
                available = limit_value - current_usage

                # Update token_usage_cache table
                await conn.execute(
                    """
                    INSERT INTO token_usage_cache (provider, used, available, limit_value, last_updated)
                    VALUES ('openai', $1, $2, $3, NOW())
                    ON CONFLICT (provider) DO UPDATE
                    SET used = $1,
                        available = $2,
                        limit_value = $3,
                        last_updated = NOW()
                    """,
                    current_usage, available, limit_value
                )

                # Log detailed usage in token_usage_log table
                if session_id or message_id:
                    await conn.execute(
                        """
                        INSERT INTO token_usage_log (session_id, message_id, provider, model, prompt_tokens, completion_tokens, total_tokens, api_call_type, created_at)
                        VALUES ($1, $2, 'openai', $3, $4, $5, $6, $7, NOW())
                        """,
                        session_id, message_id, model, input_tokens, output_tokens, total_tokens, api_call_type
                    )

                logger.debug(f"Tracked OpenAI usage: {total_tokens} tokens (input: {input_tokens}, output: {output_tokens}), total used: {current_usage}, session: {session_id}")
        else:
            logger.warning("Database not available for token tracking")
    except Exception as e:
        logger.error(f"Error tracking OpenAI token usage: {e}", exc_info=True)


async def track_gemini_usage(prompt_tokens: int, candidates_tokens: int, session_id: str = None, message_id: str = None, api_call_type: str = 'rag', model: str = 'gemini-2.5-flash-lite'):
    """
    Track Gemini token usage and update both llm_providers, token_usage_cache, and token_usage_log tables.

    Args:
        prompt_tokens: Number of prompt tokens
        candidates_tokens: Number of candidate/output tokens
        session_id: UUID of the chat session (optional)
        message_id: UUID of the chat message (optional)
        api_call_type: Type of API call ('rag', 'search', etc.)
        model: Specific model used (default: gemini-2.5-flash-lite)
    """
    if prompt_tokens <= 0 and candidates_tokens <= 0:
        return  # Skip if no tokens used

    total_tokens = prompt_tokens + candidates_tokens

    try:
        db = await get_db_connection()
        if db and hasattr(db, '_pool') and db._pool is not None:
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

                # Update token_usage_cache table
                await conn.execute(
                    """
                    INSERT INTO token_usage_cache (provider, used, available, limit_value, last_updated)
                    VALUES ('gemini', $1, $2, $3, NOW())
                    ON CONFLICT (provider) DO UPDATE
                    SET used = $1,
                        available = $2,
                        limit_value = $3,
                        last_updated = NOW()
                    """,
                    current_usage, available, limit_value
                )

                # Log detailed usage in token_usage_log table
                if session_id or message_id:
                    await conn.execute(
                        """
                        INSERT INTO token_usage_log (session_id, message_id, provider, model, prompt_tokens, completion_tokens, total_tokens, api_call_type, created_at)
                        VALUES ($1, $2, 'gemini', $3, $4, $5, $6, $7, NOW())
                        """,
                        session_id, message_id, model, prompt_tokens, candidates_tokens, total_tokens, api_call_type
                    )

                logger.debug(f"Tracked Gemini usage: {total_tokens} tokens (prompt: {prompt_tokens}, candidates: {candidates_tokens}), total used: {current_usage}, session: {session_id}")
        else:
            logger.warning("Database not available for token tracking")
    except Exception as e:
        logger.error(f"Error tracking Gemini token usage: {e}", exc_info=True)


async def track_openai_usage_from_response(usage_obj, session_id: str = None, message_id: str = None, api_call_type: str = 'chat', model: str = None):
    """
    Track OpenAI token usage from API response usage object.

    Args:
        usage_obj: OpenAI usage object with prompt_tokens, completion_tokens, total_tokens
        session_id: UUID of the chat session (optional)
        message_id: UUID of the chat message (optional)
        api_call_type: Type of API call ('chat', 'sentiment', 'summary', etc.)
        model: Specific model used (optional)
    """
    if not usage_obj:
        return

    try:
        input_tokens = getattr(usage_obj, 'prompt_tokens', 0) or getattr(usage_obj, 'input_tokens', 0) or 0
        output_tokens = getattr(usage_obj, 'completion_tokens', 0) or getattr(usage_obj, 'output_tokens', 0) or 0

        if input_tokens > 0 or output_tokens > 0:
            await track_openai_usage(input_tokens, output_tokens, session_id, message_id, api_call_type, model)
    except Exception as e:
        logger.error(f"Error extracting OpenAI usage from response: {e}", exc_info=True)


async def track_gemini_usage_from_response(usage_metadata, session_id: str = None, message_id: str = None, api_call_type: str = 'rag', model: str = 'gemini-2.5-flash-lite'):
    """
    Track Gemini token usage from API response usage_metadata.

    Args:
        usage_metadata: Gemini usage_metadata object with prompt_token_count, candidates_token_count, total_token_count
        session_id: UUID of the chat session (optional)
        message_id: UUID of the chat message (optional)
        api_call_type: Type of API call ('rag', 'search', etc.)
        model: Specific model used (default: gemini-2.5-flash-lite)
    """
    if not usage_metadata:
        return

    try:
        prompt_tokens = getattr(usage_metadata, 'prompt_token_count', 0) or 0
        candidates_tokens = getattr(usage_metadata, 'candidates_token_count', 0) or 0

        if prompt_tokens > 0 or candidates_tokens > 0:
            await track_gemini_usage(prompt_tokens, candidates_tokens, session_id, message_id, api_call_type, model)
    except Exception as e:
        logger.error(f"Error extracting Gemini usage from response: {e}", exc_info=True)

