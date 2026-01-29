"""
Feedback Endpoints
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from configuration.core.logging_config import get_railway_logger

from ..service.feedback_service import FeedbackService

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["feedback"])


class FeedbackRequest(BaseModel):
    message_id: str
    session_id: str
    feedback: Literal["positive", "negative"]


@router.post("/feedback", response_model=dict)
async def submit_feedback(request: FeedbackRequest, current_user: dict = Depends(get_current_user)):
    """Submit feedback for a chat message."""
    try:
        service = FeedbackService()  # Service manages its own DAO
        result = await service.submit_feedback(
            request.message_id, 
            request.session_id, 
            request.feedback,
            current_user.get('email')
        )
        
        return result
    except Exception as e:
        logger.error(f"Error submitting feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error submitting feedback: {str(e)}")
