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
from ..servcie.service_factory import ServiceFactory

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["feedback"])


class FeedbackRequest(BaseModel):
    message_id: str
    session_id: str
    feedback: Literal["positive", "negative"]


@router.post("/feedback", response_model=dict)
async def submit_feedback(request: FeedbackRequest):
    """Submit feedback for a chat message."""
    try:
        service = await ServiceFactory.create_feedback_service()
        result = await service.submit_feedback(
            request.message_id, 
            request.session_id, 
            request.feedback
        )
        
        return result
    except Exception as e:
        logger.error(f"Error submitting feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error submitting feedback: {str(e)}")
