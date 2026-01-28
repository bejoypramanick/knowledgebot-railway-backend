"""
Token Usage Endpoints
"""
from fastapi import APIRouter, HTTPException
import httpx
import os
import logging
from typing import Optional

from shared.auth_middleware import get_current_user
from ..service.token_usage_service import TokenUsageService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["token-usage"])


@router.get("/token-usage", response_model=dict)
async def get_token_usage(current_user: dict = Depends(get_current_user)):
    """Get token usage statistics."""
    try:
        service = TokenUsageService()  # Service manages its own DAO
        result = await service.get_gemini_usage()
        return result
    except Exception as e:
        logger.error(f"Error fetching token usage: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching token usage: {str(e)}")


@router.get("/token-usage/detailed", response_model=dict)
async def get_detailed_token_usage(limit: int = 50, provider: str = None, api_call_type: str = None, current_user: dict = Depends(get_current_user)):
    """Get detailed token usage log with correlations to specific requests."""
    try:
        service = TokenUsageService()  # Service manages its own DAO
        result = await service.get_detailed_token_usage(limit, provider, api_call_type)
        return result
    except Exception as e:
        logger.error(f"Error getting detailed token usage: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching detailed token usage: {str(e)}")

