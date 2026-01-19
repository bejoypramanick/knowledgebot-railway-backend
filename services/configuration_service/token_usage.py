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
    logger.info(f"🔍 Checking database connection: railway_db={railway_db is not None}, has_pool={hasattr(railway_db, '_pool') if railway_db else False}, pool_not_none={railway_db._pool is not None if railway_db and hasattr(railway_db, '_pool') else False}")

    if railway_db is not None and hasattr(railway_db, '_pool') and railway_db._pool is not None:
        logger.info("✅ Using existing database connection")
        return railway_db

    # Initialize database if not already initialized
    database_url = os.getenv("DATABASE_URL") or os.getenv("RAILWAY_POSTGRES_URL") or os.getenv("POSTGRES_URL")
    logger.info(f"🔍 Database URL available: {database_url is not None}")
    if database_url:
        logger.info("🔄 Initializing database connection...")
        db_instance = await init_railway_db(database_url)
        logger.info(f"✅ Database initialized: db_instance={db_instance is not None}, railway_db={railway_db is not None}")
        # Use the returned instance, but also ensure global variable is set
        if db_instance and not railway_db:
            railway_db = db_instance
        return db_instance or railway_db

    logger.warning("❌ No database connection available")
    return None


async def get_gemini_usage() -> dict:
    """Get Gemini API token usage from cache or llm_providers table."""
    logger.info("🔍 get_gemini_usage called")
    try:
        db = await get_db_connection()
        if db and hasattr(db, '_pool') and db._pool is not None:
            logger.info("✅ Database connection available for Gemini usage")
            async with db.acquire() as conn:
                # First try token_usage_cache table
                query = """
                    SELECT used, available, limit_value
                    FROM token_usage_cache
                    WHERE provider = 'gemini'
                    ORDER BY last_updated DESC
                    LIMIT 1
                    """
                logger.info(f"🔍 Executing query on token_usage_cache: {query.strip()}")
                cached = await conn.fetchrow(query)
                if cached:
                    logger.info(f"Found Gemini usage in cache: used={cached['used']}, available={cached['available']}, limit={cached['limit_value']}")
                    return {
                        "used": cached['used'] or 0,
                        "available": cached['available'] or 20000,
                        "limit": cached['limit_value'] or 20000
                    }

                # Fallback to llm_providers table
                query = """
                    SELECT
                        COALESCE(token_used, 0) as used,
                        COALESCE(token_limit, 20000) as limit_value
                    FROM llm_providers
                    WHERE provider_name = 'gemini' AND is_active = true
                    """
                logger.info(f"🔍 Executing query on llm_providers: {query.strip()}")
                config = await conn.fetchrow(query)
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
        logger.error(f"❌ Exception in get_gemini_usage: {e}", exc_info=True)
        import traceback
        logger.error(f"❌ Full traceback: {traceback.format_exc()}")
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
    logger.info("🔍 get_openai_usage called")
    try:
        db = await get_db_connection()
        if db and hasattr(db, '_pool') and db._pool is not None:
            logger.info("✅ Database connection available for OpenAI usage")
            async with db.acquire() as conn:
                # First try token_usage_cache table
                query = """
                    SELECT used, available, limit_value
                    FROM token_usage_cache
                    WHERE provider = 'openai'
                    ORDER BY last_updated DESC
                    LIMIT 1
                    """
                logger.info(f"🔍 Executing query on token_usage_cache: {query.strip()}")
                cached = await conn.fetchrow(query)
                if cached:
                    logger.info(f"Found OpenAI usage in cache: used={cached['used']}, available={cached['available']}, limit={cached['limit_value']}")
                    return {
                        "used": cached['used'] or 0,
                        "available": cached['available'] or 150000,
                        "limit": cached['limit_value'] or 150000
                    }

                # Fallback to llm_providers table (using deepseek provider for backward compatibility)
                query = """
                    SELECT
                        COALESCE(token_used, 0) as used,
                        COALESCE(token_limit, 150000) as limit_value
                    FROM llm_providers
                    WHERE provider_name = 'deepseek' AND is_active = true
                    """
                logger.info(f"🔍 Executing query on llm_providers: {query.strip()}")
                config = await conn.fetchrow(query)
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
        logger.error(f"❌ Exception in get_openai_usage: {e}", exc_info=True)
        import traceback
        logger.error(f"❌ Full traceback: {traceback.format_exc()}")
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
    logger.info("🔍 get_token_usage endpoint called")
    try:
        # Initialize token usage if needed
        await initialize_token_usage_if_needed()

        gemini_usage = await get_gemini_usage()
        openai_usage = await get_openai_usage()

        logger.info(f"✅ Token usage retrieved: gemini={gemini_usage}, openai={openai_usage}")
        return {
            "gemini": gemini_usage,
            "openai": openai_usage
        }
    except Exception as e:
        logger.error(f"Error fetching token usage: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching token usage: {str(e)}")


@router.get("/token-usage/detailed", response_model=dict)
async def get_detailed_token_usage(limit: int = 50, provider: str = None, api_call_type: str = None):
    """Get detailed token usage log with correlations to specific requests."""
    try:
        db = await get_db_connection()
        if db and hasattr(db, '_pool') and db._pool is not None:
            async with db.acquire() as conn:
                # Build query with optional filters
                query = """
                    SELECT
                        tul.id,
                        tul.provider,
                        tul.model,
                        tul.prompt_tokens,
                        tul.completion_tokens,
                        tul.total_tokens,
                        tul.api_call_type,
                        tul.created_at,
                        cs.customer_name,
                        cs.customer_email,
                        cm.content as message_preview
                    FROM token_usage_log tul
                    LEFT JOIN chat_sessions cs ON tul.session_id = cs.id
                    LEFT JOIN chat_messages cm ON tul.message_id = cm.id AND cm.role = 'user'
                    WHERE 1=1
                """

                params = []
                param_count = 0

                if provider:
                    param_count += 1
                    query += f" AND tul.provider = ${param_count}"
                    params.append(provider)

                if api_call_type:
                    param_count += 1
                    query += f" AND tul.api_call_type = ${param_count}"
                    params.append(api_call_type)

                query += f" ORDER BY tul.created_at DESC LIMIT ${param_count + 1}"
                params.append(limit)

                logger.info(f"🔍 Executing detailed token usage query: {query.strip()} | Params: {params}")
                rows = await conn.fetch(query, *params)

                # Format the results
                detailed_usage = []
                for row in rows:
                    usage_entry = {
                        "id": str(row['id']),
                        "provider": row['provider'],
                        "model": row['model'],
                        "api_call_type": row['api_call_type'],
                        "created_at": row['created_at'].isoformat() if row['created_at'] else None,
                        "session_info": {
                            "customer_name": row['customer_name'],
                            "customer_email": row['customer_email']
                        } if row['customer_name'] or row['customer_email'] else None,
                        "message_preview": row['message_preview'][:100] + "..." if row['message_preview'] and len(row['message_preview']) > 100 else row['message_preview']
                    }

                    # Add provider-specific token fields
                    if row['provider'] == 'openai':
                        usage_entry.update({
                            "input_tokens": row['prompt_tokens'] or 0,
                            "output_tokens": row['completion_tokens'] or 0,
                            "total_tokens": row['total_tokens'] or 0,
                            "cache_read_tokens": row.get('cache_read_tokens', 0) or 0,
                            "cache_write_tokens": row.get('cache_write_tokens', 0) or 0,
                            "input_audio_tokens": row.get('input_audio_tokens', 0) or 0,
                            "cache_audio_read_tokens": row.get('cache_audio_read_tokens', 0) or 0,
                        })
                    elif row['provider'] == 'gemini':
                        usage_entry.update({
                            "promptTokenCount": row['prompt_tokens'] or 0,
                            "candidatesTokenCount": row['completion_tokens'] or 0,
                            "totalTokenCount": row['total_tokens'] or 0,
                            "cache_read_tokens": row.get('cache_read_tokens', 0) or 0,
                            "cache_write_tokens": row.get('cache_write_tokens', 0) or 0,
                        })

                    detailed_usage.append(usage_entry)

                return {
                    "detailed_usage": detailed_usage,
                    "total_count": len(detailed_usage),
                    "filters_applied": {
                        "provider": provider,
                        "api_call_type": api_call_type,
                        "limit": limit
                    }
                }
        else:
            return {
                "detailed_usage": [],
                "total_count": 0,
                "error": "Database not available"
            }
    except Exception as e:
        logger.error(f"Error fetching detailed token usage: {e}", exc_info=True)
        return {
            "detailed_usage": [],
            "total_count": 0,
            "error": str(e)
        }

