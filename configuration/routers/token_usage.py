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
from shared.auth_middleware import get_current_user
from ..servcie.token_usage_service import TokenUsageService
from shared.dao.token_dao import TokenDAO

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["token-usage"])


@router.get("/token-usage", response_model=dict)
async def get_token_usage(current_user: dict = Depends(get_current_user)):
    """Get token usage statistics."""
    try:
        token_dao = TokenDAO()
        service = TokenUsageService(token_dao)
        result = await service.get_gemini_usage()
        return result
    except Exception as e:
        logger.error(f"Error fetching token usage: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching token usage: {str(e)}")


@router.get("/token-usage/detailed", response_model=dict)
async def get_detailed_token_usage(limit: int = 50, provider: str = None, api_call_type: str = None, current_user: dict = Depends(get_current_user)):
    """Get detailed token usage log with correlations to specific requests."""
    try:
        token_dao = TokenDAO()
        service = TokenUsageService(token_dao)
        result = await service.get_detailed_token_usage(limit, provider, api_call_type)
        return result
    except Exception as e:
        logger.error(f"Error getting detailed token usage: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching detailed token usage: {str(e)}")

