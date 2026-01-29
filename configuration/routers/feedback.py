"""
Feedback Endpoints
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from configuration.core.logging_config import get_railway_logger
from configuration.core.auth_middleware import require_auth

from ..service.feedback_service import FeedbackService

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["feedback"])


class FeedbackRequest(BaseModel):
    message_id: str
    session_id: str
    feedback: Literal["positive", "negative"]


@router.post("/feedback")
async def submit_feedback(
    request: FeedbackRequest,
    current_user: dict = Depends(get_current_user)
):
    """Submit feedback for a chat message."""
    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=400, detail="User email required")
    
    try:
        service = FeedbackService()
        result = await service.submit_feedback(
            message_id=request.message_id,
            session_id=request.session_id,
            feedback=request.feedback,
            user_email=user_email
        )
        return result
    except Exception as e:
        logger.error(f"Error submitting feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error submitting feedback: {str(e)}")
