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
    await track_openai_usage_detailed(
        input_tokens=input_tokens,
        output_tokens=output_tokens,
        cache_read_tokens=0,
        cache_write_tokens=0,
        input_audio_tokens=0,
        cache_audio_read_tokens=0,
        session_id=session_id,
        message_id=message_id,
        api_call_type=api_call_type,
        model=model
    )


async def track_openai_usage_detailed(
    input_tokens: int,
    output_tokens: int,
    cache_read_tokens: int = 0,
    cache_write_tokens: int = 0,
    input_audio_tokens: int = 0,
    cache_audio_read_tokens: int = 0,
    session_id: str = None,
    message_id: str = None,
    api_call_type: str = 'chat',
    model: str = None
):
    """
    Track detailed OpenAI token usage with cache and audio token breakdown.

    Args:
        input_tokens: Number of input/prompt tokens
        output_tokens: Number of output/completion tokens
        cache_read_tokens: Tokens read from cache
        cache_write_tokens: Tokens written to cache
        input_audio_tokens: Audio input tokens
        cache_audio_read_tokens: Audio tokens read from cache
        session_id: UUID of the chat session (optional)
        message_id: UUID of the chat message (optional)
        api_call_type: Type of API call ('chat', 'sentiment', 'summary', etc.)
        model: Specific model used (optional)
    """
    if input_tokens <= 0 and output_tokens <= 0 and cache_read_tokens <= 0 and cache_write_tokens <= 0:
        return  # Skip if no tokens used

    total_tokens = input_tokens + output_tokens + cache_read_tokens + cache_write_tokens

    try:
        db = await get_db_connection()
        if db and hasattr(db, '_pool') and db._pool is not None:
            async with db.acquire() as conn:
                # First, update llm_providers table
                await conn.execute(
                    """
                    INSERT INTO llm_providers (provider_name, token_used, token_limit, is_active)
                    VALUES ('openai', $1, 150000, true)
                    ON CONFLICT (provider_name) DO UPDATE
                    SET token_used = COALESCE(llm_providers.token_used, 0) + $1,
                        token_limit = COALESCE(llm_providers.token_limit, 150000),
                        is_active = true
                    """,
                    total_tokens
                )

                # Get current usage from llm_providers for calculation
                current_usage = await conn.fetchval(
                    "SELECT COALESCE(token_used, 0) FROM llm_providers WHERE provider_name = 'openai'"
                ) or 0

                limit_value = 150000
                available = limit_value - current_usage

                # Update token_usage_cache table
                cache_query = """
                    INSERT INTO token_usage_cache (provider, used, available, limit_value, last_updated)
                    VALUES ('openai', $1, $2, $3, NOW())
                    ON CONFLICT (provider) DO UPDATE
                    SET used = $1,
                        available = $2,
                        limit_value = $3,
                        last_updated = NOW()
                    """
                logger.info(f"🔍 Executing INSERT on token_usage_cache (track_openai_usage_detailed): {cache_query.strip()} | Params: [{current_usage}, {available}, {limit_value}]")
                await conn.execute(cache_query, current_usage, available, limit_value)

                # Log detailed usage in token_usage_log table
                if session_id or message_id:
                    log_query = """
                        INSERT INTO token_usage_log (
                            session_id, message_id, provider, model, prompt_tokens, completion_tokens,
                            total_tokens, cache_read_tokens, cache_write_tokens, input_audio_tokens,
                            cache_audio_read_tokens, api_call_type, created_at
                        )
                        VALUES ($1, $2, 'openai', $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW())
                        """
                    logger.info(f"🔍 Executing INSERT on token_usage_log (track_openai_usage_detailed): {log_query.strip()} | Params: [{session_id}, {message_id}, 'openai', {model}, {input_tokens}, {output_tokens}, {total_tokens}, {cache_read_tokens}, {cache_write_tokens}, {input_audio_tokens}, {cache_audio_read_tokens}, '{api_call_type}']")
                    await conn.execute(log_query,
                        session_id, message_id, model, input_tokens, output_tokens, total_tokens,
                        cache_read_tokens, cache_write_tokens, input_audio_tokens, cache_audio_read_tokens, api_call_type
                    )

                logger.info(f"✅ Tracked OpenAI detailed usage: {total_tokens} tokens (input: {input_tokens}, output: {output_tokens}, cache_read: {cache_read_tokens}, cache_write: {cache_write_tokens}), total used: {current_usage}, session: {session_id}")
        else:
            logger.warning("Database not available for token tracking")
    except Exception as e:
        logger.error(f"Error tracking OpenAI detailed token usage: {e}", exc_info=True)


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
    if prompt_tokens <= 0 and candidates_tokens <= 0 and cache_read_tokens <= 0 and cache_write_tokens <= 0:
        return  # Skip if no tokens used

    total_tokens = prompt_tokens + candidates_tokens + cache_read_tokens + cache_write_tokens

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
                cache_query = """
                    INSERT INTO token_usage_cache (provider, used, available, limit_value, last_updated)
                    VALUES ('gemini', $1, $2, $3, NOW())
                    ON CONFLICT (provider) DO UPDATE
                    SET used = $1,
                        available = $2,
                        limit_value = $3,
                        last_updated = NOW()
                    """
                logger.info(f"🔍 Executing INSERT on token_usage_cache (track_gemini_usage_detailed): {cache_query.strip()} | Params: [{current_usage}, {available}, {limit_value}]")
                await conn.execute(cache_query, current_usage, available, limit_value)

                # Log detailed usage in token_usage_log table
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

                logger.info(f"✅ Tracked Gemini detailed usage: {total_tokens} tokens (prompt: {prompt_tokens}, candidates: {candidates_tokens}, cache_read: {cache_read_tokens}, cache_write: {cache_write_tokens}), total used: {current_usage}, session: {session_id}")
        else:
            logger.warning("Database not available for token tracking")
    except Exception as e:
        logger.error(f"Error tracking Gemini detailed token usage: {e}", exc_info=True)


async def track_openai_usage_from_response(usage_obj, session_id: str = None, message_id: str = None, api_call_type: str = 'chat', model: str = None):
    """
    Track OpenAI token usage from API response usage object.

    Args:
        usage_obj: OpenAI usage object with detailed token breakdown
        session_id: UUID of the chat session (optional)
        message_id: UUID of the chat message (optional)
        api_call_type: Type of API call ('chat', 'sentiment', 'summary', etc.)
        model: Specific model used (optional)
    """
    logger.info(f"🔍 Token tracking called for OpenAI - session: {session_id}, message: {message_id}, type: {api_call_type}, model: {model}")

    if not usage_obj:
        logger.warning("⚠️ OpenAI usage object is None or empty")
        return

    try:
        # Extract detailed token breakdown from RunUsage object (from pydantic-ai)
        input_tokens = getattr(usage_obj, 'input_tokens', 0) or getattr(usage_obj, 'prompt_tokens', 0) or 0
        output_tokens = getattr(usage_obj, 'output_tokens', 0) or getattr(usage_obj, 'completion_tokens', 0) or 0
        cache_read_tokens = getattr(usage_obj, 'cache_read_tokens', 0) or 0
        cache_write_tokens = getattr(usage_obj, 'cache_write_tokens', 0) or 0
        input_audio_tokens = getattr(usage_obj, 'input_audio_tokens', 0) or 0
        cache_audio_read_tokens = getattr(usage_obj, 'cache_audio_read_tokens', 0) or 0

        logger.info(f"📊 OpenAI detailed usage - input: {input_tokens}, output: {output_tokens}, cache_read: {cache_read_tokens}, cache_write: {cache_write_tokens}, audio: {input_audio_tokens}")

        if input_tokens > 0 or output_tokens > 0 or cache_read_tokens > 0 or cache_write_tokens > 0:
            await track_openai_usage_detailed(
                input_tokens=input_tokens,
                output_tokens=output_tokens,
                cache_read_tokens=cache_read_tokens,
                cache_write_tokens=cache_write_tokens,
                input_audio_tokens=input_audio_tokens,
                cache_audio_read_tokens=cache_audio_read_tokens,
                session_id=session_id,
                message_id=message_id,
                api_call_type=api_call_type,
                model=model
            )
            logger.info("✅ OpenAI detailed token tracking completed successfully")
        else:
            logger.warning("⚠️ No token usage to track (zero tokens)")
    except Exception as e:
        logger.error(f"❌ Error extracting OpenAI usage from response: {e}", exc_info=True)


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

    if not usage_obj:
        logger.warning("⚠️ Gemini usage object is None or empty")
        return

    try:
        # Extract detailed token breakdown from RunUsage object (from pydantic-ai)
        # Gemini typically uses different field names than OpenAI
        prompt_tokens = getattr(usage_obj, 'input_tokens', 0) or getattr(usage_obj, 'prompt_tokens', 0) or getattr(usage_obj, 'prompt_token_count', 0) or 0
        candidates_tokens = getattr(usage_obj, 'output_tokens', 0) or getattr(usage_obj, 'completion_tokens', 0) or getattr(usage_obj, 'candidates_token_count', 0) or 0
        cache_read_tokens = getattr(usage_obj, 'cache_read_tokens', 0) or 0
        cache_write_tokens = getattr(usage_obj, 'cache_write_tokens', 0) or 0

        logger.info(f"📊 Gemini detailed usage - prompt: {prompt_tokens}, candidates: {candidates_tokens}, cache_read: {cache_read_tokens}, cache_write: {cache_write_tokens}")

        if prompt_tokens > 0 or candidates_tokens > 0 or cache_read_tokens > 0 or cache_write_tokens > 0:
            await track_gemini_usage_detailed(
                prompt_tokens=prompt_tokens,
                candidates_tokens=candidates_tokens,
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


async def track_openai_usage_with_db(run_usage, session_id: str = None, message_id: str = None, api_call_type: str = 'rag', model: str = 'gpt-4o', db_connection=None):
    """
    Track OpenAI token usage using an existing database connection.
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
        # Extract token counts from RunUsage object
        input_tokens = getattr(run_usage, 'input_tokens', 0)
        output_tokens = getattr(run_usage, 'output_tokens', 0)
        cache_read_tokens = getattr(run_usage, 'details', {}).get('accepted_prediction_tokens', 0)
        cache_write_tokens = getattr(run_usage, 'details', {}).get('rejected_prediction_tokens', 0)
        input_audio_tokens = getattr(run_usage, 'details', {}).get('audio_tokens', 0)
        cache_audio_read_tokens = getattr(run_usage, 'details', {}).get('reasoning_tokens', 0)

        if input_tokens <= 0 and output_tokens <= 0 and cache_read_tokens <= 0 and cache_write_tokens <= 0:
            logger.warning("⚠️ No token usage to track (zero tokens)")
            return

        total_tokens = input_tokens + output_tokens + cache_read_tokens + cache_write_tokens

        # Use the provided database connection
        if db_connection:
            async with db_connection.acquire() as conn:
                # First, update llm_providers table
                await conn.execute(
                    """
                    INSERT INTO llm_providers (provider_name, token_used, token_limit, is_active)
                    VALUES ('openai', $1, 150000, true)
                    ON CONFLICT (provider_name) DO UPDATE
                    SET token_used = COALESCE(llm_providers.token_used, 0) + $1,
                        token_limit = COALESCE(llm_providers.token_limit, 150000),
                        is_active = true
                    """,
                    total_tokens
                )

                # Get current usage from llm_providers for calculation
                current_usage = await conn.fetchval(
                    "SELECT COALESCE(token_used, 0) FROM llm_providers WHERE provider_name = 'openai'"
                ) or 0

                limit_value = 150000
                available = limit_value - current_usage

                # Update token_usage_cache table
                cache_query = """
                    INSERT INTO token_usage_cache (provider, used, available, limit_value, last_updated)
                    VALUES ('openai', $1, $2, $3, NOW())
                    ON CONFLICT (provider) DO UPDATE
                    SET used = $1,
                        available = $2,
                        limit_value = $3,
                        last_updated = NOW()
                    """
                logger.info(f"🔍 Executing INSERT on token_usage_cache (track_openai_usage_with_db): {cache_query.strip()} | Params: [{current_usage}, {available}, {limit_value}]")
                await conn.execute(cache_query, current_usage, available, limit_value)

                # Log detailed usage in token_usage_log table
                if session_id or message_id:
                    log_query = """
                        INSERT INTO token_usage_log (
                            session_id, message_id, provider, model, prompt_tokens, completion_tokens,
                            total_tokens, cache_read_tokens, cache_write_tokens, input_audio_tokens,
                            cache_audio_read_tokens, api_call_type, created_at
                        )
                        VALUES ($1, $2, 'openai', $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW())
                        """
                    logger.info(f"🔍 Executing INSERT on token_usage_log (track_openai_usage_with_db): {log_query.strip()} | Params: [{session_id}, {message_id}, 'openai', {model}, {input_tokens}, {output_tokens}, {total_tokens}, {cache_read_tokens}, {cache_write_tokens}, {input_audio_tokens}, {cache_audio_read_tokens}, '{api_call_type}']")
                    await conn.execute(log_query,
                        session_id, message_id, model, input_tokens, output_tokens, total_tokens,
                        cache_read_tokens, cache_write_tokens, input_audio_tokens, cache_audio_read_tokens, api_call_type
                    )

                logger.info(f"✅ Tracked OpenAI detailed usage with provided DB: {total_tokens} tokens (input: {input_tokens}, output: {output_tokens}, cache_read: {cache_read_tokens}, cache_write: {cache_write_tokens}), total used: {current_usage}, session: {session_id}")
        else:
            logger.warning("No database connection provided for token tracking")
    except Exception as e:
        logger.error(f"❌ Error tracking OpenAI detailed token usage with provided DB: {e}", exc_info=True)


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

                # Update token_usage_cache table
                cache_query = """
                    INSERT INTO token_usage_cache (provider, used, available, limit_value, last_updated)
                    VALUES ('gemini', $1, $2, $3, NOW())
                    ON CONFLICT (provider) DO UPDATE
                    SET used = $1,
                        available = $2,
                        limit_value = $3,
                        last_updated = NOW()
                    """
                logger.info(f"🔍 Executing INSERT on token_usage_cache (track_gemini_usage_with_db): {cache_query.strip()} | Params: [{current_usage}, {available}, {limit_value}]")
                await conn.execute(cache_query, current_usage, available, limit_value)

                # Log detailed usage in token_usage_log table
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

