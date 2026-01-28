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
from .main import get_db_connection
from .dao.feedback_dao import FeedbackDAO

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["feedback"])


class FeedbackRequest(BaseModel):
    message_id: str
    session_id: str
    feedback: Literal["positive", "negative"]


# Removed update_session_feedback function - session feedback is now computed on-the-fly


@router.post("/feedback", response_model=dict)
async def submit_feedback(request: FeedbackRequest):
    """Submit feedback for a chat message."""
    try:
        async with get_db_connection() as conn:
            feedback_dao = FeedbackDAO(conn)
            
            # Security check: Verify the message actually belongs to this session
            actual_session_id = await feedback_dao.verify_message_session(request.message_id, request.session_id)
            
            if actual_session_id != request.session_id:
                logger.warning(f"Feedback submission blocked: message {request.message_id} does not belong to session {request.session_id}")
                raise HTTPException(status_code=403, detail="Message does not belong to specified session")
            
            # Insert the feedback
            await feedback_dao.insert_feedback(request.message_id, request.session_id, request.feedback)
            
            logger.info(f"Feedback recorded: {request.feedback} for message {request.message_id} in session {request.session_id}")
            
            return {
                "success": True,
                "message": "Feedback recorded successfully",
                "feedback": request.feedback
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error submitting feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error submitting feedback: {str(e)}")
