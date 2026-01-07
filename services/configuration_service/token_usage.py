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
from shared.db import railway_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["token-usage"])


async def get_gemini_usage() -> dict:
    """Get Gemini API token usage."""
    gemini_api_key = os.getenv('GEMINI_API_KEY')
    if not gemini_api_key:
        logger.warning("GEMINI_API_KEY not set, returning default values")
        return {
            "used": 0,
            "available": 20000,
            "limit": 20000
        }
    
    try:
        # Note: Gemini API doesn't have a direct usage endpoint
        # You may need to track usage manually or use Google Cloud Billing API
        # For now, return cached value from database if available
        if railway_db and hasattr(railway_db, '_pool') and railway_db._pool is not None:
            async with railway_db.acquire() as conn:
                cached = await conn.fetchrow(
                    """
                    SELECT used, available, limit_value 
                    FROM token_usage_cache 
                    WHERE provider = 'gemini'
                    """
                )
                if cached:
                    return {
                        "used": cached['used'],
                        "available": cached['available'],
                        "limit": cached['limit_value']
                    }
        
        # Default values if no cache
        return {
            "used": 0,
            "available": 20000,
            "limit": 20000
        }
    except Exception as e:
        logger.error(f"Error fetching Gemini usage: {e}")
        return {
            "used": 0,
            "available": 20000,
            "limit": 20000
        }


async def get_openai_usage() -> dict:
    """Get OpenAI API token usage."""
    openai_api_key = os.getenv('OPENAI_API_KEY')
    if not openai_api_key:
        logger.warning("OPENAI_API_KEY not set, returning default values")
        return {
            "used": 0,
            "available": 150000,
            "limit": 150000
        }
    
    try:
        # Try to get usage from OpenAI API
        # Note: OpenAI doesn't have a direct usage endpoint in their API
        # You may need to use their dashboard API or track usage manually
        # For now, return cached value from database if available
        if railway_db and hasattr(railway_db, '_pool') and railway_db._pool is not None:
            async with railway_db.acquire() as conn:
                cached = await conn.fetchrow(
                    """
                    SELECT used, available, limit_value 
                    FROM token_usage_cache 
                    WHERE provider = 'openai'
                    """
                )
                if cached:
                    return {
                        "used": cached['used'],
                        "available": cached['available'],
                        "limit": cached['limit_value']
                    }
        
        # Default values if no cache
        return {
            "used": 0,
            "available": 150000,
            "limit": 150000
        }
    except Exception as e:
        logger.error(f"Error fetching OpenAI usage: {e}")
        return {
            "used": 0,
            "available": 150000,
            "limit": 150000
        }


@router.get("/token-usage", response_model=dict)
async def get_token_usage():
    """Get token usage for Gemini and OpenAI."""
    try:
        gemini_usage = await get_gemini_usage()
        openai_usage = await get_openai_usage()
        
        return {
            "gemini": gemini_usage,
            "openai": openai_usage
        }
    except Exception as e:
        logger.error(f"Error fetching token usage: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching token usage: {str(e)}")

