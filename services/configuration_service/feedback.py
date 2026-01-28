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
from shared.db import railway_db

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
    if not railway_db or not hasattr(railway_db, '_pool') or railway_db._pool is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    try:
        async with railway_db.acquire() as conn:
            # Security check: Verify the message actually belongs to this session
            # This prevents spoofing feedback for other sessions
            actual_session_id = await conn.fetchval(
                "SELECT session_id FROM chat_messages WHERE id::text = $1 LIMIT 1",
                request.message_id
            )
            
            if not actual_session_id:
                # Try without casting if id is not UUID
                actual_session_id = await conn.fetchval(
                    "SELECT session_id FROM chat_messages WHERE id = $1 LIMIT 1",
                    request.message_id
                )

            if not actual_session_id or actual_session_id != request.session_id:
                logger.warning(f"Feedback session mismatch: message {request.message_id} (session {actual_session_id}) != request session {request.session_id}")
                raise HTTPException(status_code=400, detail="Invalid session_id for this message")

            # Insert feedback
            await conn.execute(
                """
                INSERT INTO chat_feedback (message_id, session_id, feedback_type)
                VALUES ($1, $2, $3)
                """,
                request.message_id, request.session_id, request.feedback
            )
            
            logger.info(f"Feedback recorded: {request.feedback} for message {request.message_id} in session {request.session_id}")
            
            return {
                "success": True,
                "message": "Feedback recorded"
            }
    except Exception as e:
        logger.error(f"Error recording feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error recording feedback: {str(e)}")

