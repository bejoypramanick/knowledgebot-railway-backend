"""
Feedback Endpoints
"""
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel

from configuration.core.logging_config import get_railway_logger

from ..service.feedback_service import FeedbackService

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1", tags=["feedback"])


class FeedbackRequest(BaseModel):
    message_id: str
    session_id: str
    feedback: Literal["positive", "negative"]


@router.post("/submit")
async def submit_feedback(request: Request, feedback_request: FeedbackRequest):
    """Submit feedback for a chat message."""
    
    try:
        # Get user email from headers (set by API Gateway)
        user_email = request.headers.get("X-User-Email", "")
        
        service = FeedbackService()
        result = await service.submit_feedback(
            message_id=feedback_request.message_id,
            session_id=feedback_request.session_id,
            feedback=feedback_request.feedback,
            user_email=user_email
        )
        return result
    except Exception as e:
        logger.error(f"Error submitting feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error submitting feedback: {str(e)}")
