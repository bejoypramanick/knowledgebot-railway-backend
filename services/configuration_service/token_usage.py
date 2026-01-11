"""
Token Usage Endpoints
"""
from fastapi import APIRouter, HTTPException
import httpx
import os
import logging
import sys
from pathlib import Path
from typing import Optional

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.db import railway_db, init_railway_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["token-usage"])


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


async def get_gemini_usage() -> dict:
    """Get Gemini API token usage from cache or llm_providers table."""
    try:
        db = await get_db_connection()
        if db and hasattr(db, '_pool') and db._pool is not None:
            async with db.acquire() as conn:
                # First try token_usage_cache table
                cached = await conn.fetchrow(
                    """
                    SELECT used, available, limit_value
                    FROM token_usage_cache
                    WHERE provider = 'gemini'
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                )
                if cached:
                    logger.info(f"Found Gemini usage in cache: used={cached['used']}, available={cached['available']}, limit={cached['limit_value']}")
                    return {
                        "used": cached['used'] or 0,
                        "available": cached['available'] or 20000,
                        "limit": cached['limit_value'] or 20000
                    }

                # Fallback to llm_providers table
                config = await conn.fetchrow(
                    """
                    SELECT
                        COALESCE(token_used, 0) as used,
                        COALESCE(token_limit, 20000) as limit_value
                    FROM llm_providers
                    WHERE provider_name = 'gemini' AND is_active = true
                    """
                )
                if config:
                    used = config['used']
                    limit = config['limit_value']
                    available = limit - used
                    logger.info(f"Found Gemini usage in llm_providers: used={used}, available={available}, limit={limit}")
                    return {
                        "used": used,
                        "available": available,
                        "limit": limit
                    }

        # Default values if no data found
        logger.warning("No Gemini usage data found, returning defaults")
        return {
            "used": 0,
            "available": 20000,
            "limit": 20000
        }
    except Exception as e:
        logger.error(f"Error fetching Gemini usage: {e}", exc_info=True)
        return {
            "used": 0,
            "available": 20000,
            "limit": 20000
        }


async def get_openai_usage() -> dict:
    """Get OpenAI API token usage from cache or llm_providers table."""
    try:
        db = await get_db_connection()
        if db and hasattr(db, '_pool') and db._pool is not None:
            async with db.acquire() as conn:
                # First try token_usage_cache table
                cached = await conn.fetchrow(
                    """
                    SELECT used, available, limit_value
                    FROM token_usage_cache
                    WHERE provider = 'openai'
                    ORDER BY updated_at DESC
                    LIMIT 1
                    """
                )
                if cached:
                    logger.info(f"Found OpenAI usage in cache: used={cached['used']}, available={cached['available']}, limit={cached['limit_value']}")
                    return {
                        "used": cached['used'] or 0,
                        "available": cached['available'] or 150000,
                        "limit": cached['limit_value'] or 150000
                    }

                # Fallback to llm_providers table (using deepseek provider for backward compatibility)
                config = await conn.fetchrow(
                    """
                    SELECT
                        COALESCE(token_used, 0) as used,
                        COALESCE(token_limit, 150000) as limit_value
                    FROM llm_providers
                    WHERE provider_name = 'deepseek' AND is_active = true
                    """
                )
                if config:
                    used = config['used']
                    limit = config['limit_value']
                    available = limit - used
                    logger.info(f"Found OpenAI usage in llm_providers: used={used}, available={available}, limit={limit}")
                    return {
                        "used": used,
                        "available": available,
                        "limit": limit
                    }

        # Default values if no data found
        logger.warning("No OpenAI usage data found, returning defaults")
        return {
            "used": 0,
            "available": 150000,
            "limit": 150000
        }
    except Exception as e:
        logger.error(f"Error fetching OpenAI usage: {e}", exc_info=True)
        return {
            "used": 0,
            "available": 150000,
            "limit": 150000
        }


async def initialize_token_usage_if_needed():
    """Initialize token usage in llm_providers table if not set."""
    try:
        db = await get_db_connection()
        if db and hasattr(db, '_pool') and db._pool is not None:
            async with db.acquire() as conn:
                # Initialize Gemini provider
                await conn.execute(
                    """
                    INSERT INTO llm_providers (provider_name, token_limit, token_used, is_active)
                    VALUES ('gemini', 20000, 0, true)
                    ON CONFLICT (provider_name) DO UPDATE SET
                        token_limit = COALESCE(llm_providers.token_limit, 20000),
                        is_active = true
                    """
                )

                # Initialize DeepSeek provider (used for OpenAI compatibility)
                await conn.execute(
                    """
                    INSERT INTO llm_providers (provider_name, token_limit, token_used, is_active)
                    VALUES ('deepseek', 150000, 0, true)
                    ON CONFLICT (provider_name) DO UPDATE SET
                        token_limit = COALESCE(llm_providers.token_limit, 150000),
                        is_active = true
                    """
                )
                logger.info("Ensured token usage limits are initialized in llm_providers table")
    except Exception as e:
        logger.error(f"Error initializing token usage: {e}", exc_info=True)


@router.get("/token-usage", response_model=dict)
async def get_token_usage():
    """Get token usage for Gemini and OpenAI."""
    try:
        # Initialize token usage if needed
        await initialize_token_usage_if_needed()
        
        gemini_usage = await get_gemini_usage()
        openai_usage = await get_openai_usage()
        
        return {
            "gemini": gemini_usage,
            "openai": openai_usage
        }
    except Exception as e:
        logger.error(f"Error fetching token usage: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching token usage: {str(e)}")

