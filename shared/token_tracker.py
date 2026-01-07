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


async def track_openai_usage(input_tokens: int, output_tokens: int):
    """
    Track OpenAI token usage and update the database.
    
    Args:
        input_tokens: Number of input/prompt tokens
        output_tokens: Number of output/completion tokens
    """
    if input_tokens <= 0 and output_tokens <= 0:
        return  # Skip if no tokens used
    
    total_tokens = input_tokens + output_tokens
    
    try:
        db = await get_db_connection()
        if db and hasattr(db, '_pool') and db._pool is not None:
            async with db.acquire() as conn:
                # Atomically increment token usage
                await conn.execute(
                    """
                    INSERT INTO chatbot_configuration (admin_user, llm_token_used_deepseek, llm_token_limit_deepseek)
                    VALUES ('GLOBISTAAN', $1, 150000)
                    ON CONFLICT (admin_user) DO UPDATE
                    SET llm_token_used_deepseek = COALESCE(chatbot_configuration.llm_token_used_deepseek, 0) + $1,
                        llm_token_limit_deepseek = COALESCE(chatbot_configuration.llm_token_limit_deepseek, 150000)
                    """,
                    total_tokens
                )
                logger.debug(f"Tracked OpenAI usage: {total_tokens} tokens (input: {input_tokens}, output: {output_tokens})")
        else:
            logger.warning("Database not available for token tracking")
    except Exception as e:
        logger.error(f"Error tracking OpenAI token usage: {e}", exc_info=True)


async def track_gemini_usage(prompt_tokens: int, candidates_tokens: int):
    """
    Track Gemini token usage and update the database.
    
    Args:
        prompt_tokens: Number of prompt tokens
        candidates_tokens: Number of candidate/output tokens
    """
    if prompt_tokens <= 0 and candidates_tokens <= 0:
        return  # Skip if no tokens used
    
    total_tokens = prompt_tokens + candidates_tokens
    
    try:
        db = await get_db_connection()
        if db and hasattr(db, '_pool') and db._pool is not None:
            async with db.acquire() as conn:
                # Atomically increment token usage
                await conn.execute(
                    """
                    INSERT INTO chatbot_configuration (admin_user, llm_token_used_gemini, llm_token_limit_gemini)
                    VALUES ('GLOBISTAAN', $1, 20000)
                    ON CONFLICT (admin_user) DO UPDATE
                    SET llm_token_used_gemini = COALESCE(chatbot_configuration.llm_token_used_gemini, 0) + $1,
                        llm_token_limit_gemini = COALESCE(chatbot_configuration.llm_token_limit_gemini, 20000)
                    """,
                    total_tokens
                )
                logger.debug(f"Tracked Gemini usage: {total_tokens} tokens (prompt: {prompt_tokens}, candidates: {candidates_tokens})")
        else:
            logger.warning("Database not available for token tracking")
    except Exception as e:
        logger.error(f"Error tracking Gemini token usage: {e}", exc_info=True)


async def track_openai_usage_from_response(usage_obj):
    """
    Track OpenAI token usage from API response usage object.
    
    Args:
        usage_obj: OpenAI usage object with prompt_tokens, completion_tokens, total_tokens
    """
    if not usage_obj:
        return
    
    try:
        input_tokens = getattr(usage_obj, 'prompt_tokens', 0) or getattr(usage_obj, 'input_tokens', 0) or 0
        output_tokens = getattr(usage_obj, 'completion_tokens', 0) or getattr(usage_obj, 'output_tokens', 0) or 0
        
        if input_tokens > 0 or output_tokens > 0:
            await track_openai_usage(input_tokens, output_tokens)
    except Exception as e:
        logger.error(f"Error extracting OpenAI usage from response: {e}", exc_info=True)


async def track_gemini_usage_from_response(usage_metadata):
    """
    Track Gemini token usage from API response usage_metadata.
    
    Args:
        usage_metadata: Gemini usage_metadata object with prompt_token_count, candidates_token_count, total_token_count
    """
    if not usage_metadata:
        return
    
    try:
        prompt_tokens = getattr(usage_metadata, 'prompt_token_count', 0) or 0
        candidates_tokens = getattr(usage_metadata, 'candidates_token_count', 0) or 0
        
        if prompt_tokens > 0 or candidates_tokens > 0:
            await track_gemini_usage(prompt_tokens, candidates_tokens)
    except Exception as e:
        logger.error(f"Error extracting Gemini usage from response: {e}", exc_info=True)

