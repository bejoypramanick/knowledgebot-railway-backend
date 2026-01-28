"""
Feedback Endpoints
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal, Optional
import logging
import sys
from pathlib import Path

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from shared.auth_middleware import get_current_user
from ..servcie.feedback_service import FeedbackService
from ..dao.feedback_dao import FeedbackDAO

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["feedback"])


class FeedbackRequest(BaseModel):
    message_id: str
    session_id: str
    feedback: Literal["positive", "negative"]


@router.post("/feedback", response_model=dict)
async def submit_feedback(request: FeedbackRequest, current_user: dict = Depends(get_current_user)):
    """Submit feedback for a chat message."""
    try:
        feedback_dao = FeedbackDAO()
        service = FeedbackService(feedback_dao)
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
