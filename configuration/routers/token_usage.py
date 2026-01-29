"""
Token Usage Endpoints
"""
from fastapi import APIRouter, Depends, HTTPException, Query

from configuration.core.logging_config import get_railway_logger

# Placeholder for authentication since it's handled at API Gateway level
def get_current_user():
    """Placeholder function - authentication is handled at API Gateway level"""
    return {"email": "system@example.com"}

from ..service.token_usage_service import TokenUsageService

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["token-usage"])


@router.get("/token-usage", response_model=dict)
async def get_token_usage(current_user: dict = Depends(get_current_user)):
    """Get token usage statistics."""
    try:
        service = TokenUsageService()
        result = await service.get_token_usage_summary()
        return result
    except Exception as e:
        logger.error(f"Error fetching token usage: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching token usage: {str(e)}")


@router.get("/token-usage/detailed", response_model=dict)
async def get_detailed_token_usage(
    limit: int = Query(50, ge=1, le=200),
    provider: str = Query(None),
    api_call_type: str = Query(None),
    current_user: dict = Depends(get_current_user)
):
    """Get detailed token usage with filtering options."""
    try:
        service = TokenUsageService()
        result = await service.get_detailed_token_usage(
            limit=limit,
            provider=provider,
            api_call_type=api_call_type
        )
        return result
    except Exception as e:
        logger.error(f"Error fetching detailed token usage: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching detailed token usage: {str(e)}")
