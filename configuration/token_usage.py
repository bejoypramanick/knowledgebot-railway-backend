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
from .main import get_db_connection
from shared.dao.token_dao import TokenDAO

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["token-usage"])


async def get_gemini_usage() -> dict:
    """Get Gemini API token usage by calculating totals from token_usage_log table."""
    logger.info(" get_gemini_usage called")
    try:
        async with get_db_connection() as conn:
            token_dao = TokenDAO(conn)
            
            # Get total used tokens from log table
            used = await token_dao.get_gemini_usage_from_log()
            
            # Get limit from llm_providers table
            limit = await token_dao.get_gemini_limit()
            available = max(0, limit - used)
            
            return {
                'used': used,
                'limit': limit,
                'available': available,
                'percentage': round((used / limit * 100), 2) if limit > 0 else 0
            }
    except Exception as e:
        logger.error(f"❌ Exception in get_gemini_usage: {e}", exc_info=True)
        import traceback
        logger.error(f"❌ Full traceback: {traceback.format_exc()}")
        raise HTTPException(status_code=500, detail=f"Error fetching Gemini usage: {str(e)}")




async def initialize_token_usage_if_needed():
    """Initialize token usage in llm_providers table if not set."""
    try:
        async with get_db_connection() as conn:
            token_dao = TokenDAO(conn)
            await token_dao.initialize_gemini_provider()
            logger.info("Ensured token usage limits are initialized in llm_providers table")
    except Exception as e:
        logger.error(f"Error initializing token usage: {e}", exc_info=True)


@router.get("/token-usage/detailed", response_model=dict)
async def get_detailed_token_usage(limit: int = 50, provider: str = None, api_call_type: str = None):
    """Get detailed token usage log with correlations to specific requests."""
    try:
        async with get_db_connection() as conn:
            token_dao = TokenDAO(conn)
            
            # Get detailed usage
            rows = await token_dao.get_detailed_token_usage(
                provider=provider,
                api_call_type=api_call_type,
                limit=limit
            )
            
            # Format the results
            detailed_usage = []
            for row in rows:
                detailed_usage.append({
                    'id': str(row['id']),
                    'provider': row['provider'],
                    'model': row['model'],
                    'api_call_type': row['api_call_type'],
                    'prompt_tokens': row['prompt_tokens'],
                    'completion_tokens': row['completion_tokens'],
                    'total_tokens': row['total_tokens'],
                    'cache_read_tokens': row['cache_read_tokens'],
                    'cache_write_tokens': row['cache_write_tokens'],
                    'created_at': row['created_at'].isoformat() if row['created_at'] else None
                })
            
            return {
                'success': True,
                'usage': detailed_usage,
                'count': len(detailed_usage)
            }
    except Exception as e:
        logger.error(f"Error getting detailed token usage: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching detailed token usage: {str(e)}")

