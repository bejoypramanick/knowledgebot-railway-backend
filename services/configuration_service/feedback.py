"""
Feedback Endpoints
"""
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from typing import Literal
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


async def update_session_feedback(session_id: str, conn):
    """
    Update session-level feedback by aggregating all feedback for the session.
    Called after feedback is submitted to update the session_feedback column.
    """
    try:
        # Count positive and negative feedback for this session
        result = await conn.fetchrow(
            """
            SELECT 
                COUNT(*) FILTER (WHERE feedback_type = 'positive') as positive_count,
                COUNT(*) FILTER (WHERE feedback_type = 'negative') as negative_count
            FROM chat_feedback
            WHERE session_id = $1
            """,
            session_id
        )
        
        if not result:
            return
        
        positive_count = result['positive_count'] or 0
        negative_count = result['negative_count'] or 0
        
        # Determine session-level feedback
        # If there's any negative feedback, mark as negative
        # Otherwise, if there's positive feedback, mark as positive
        # If no feedback, leave as NULL
        if negative_count > 0:
            final_feedback = 'negative'
        elif positive_count > 0:
            final_feedback = 'positive'
        else:
            final_feedback = None
        
        # Update the session
        await conn.execute(
            """
            UPDATE chat_sessions
            SET session_feedback = $1,
                updated_at = CURRENT_TIMESTAMP
            WHERE session_id = $2
            """,
            final_feedback, session_id
        )
        
        logger.debug(f"Updated session_feedback to '{final_feedback}' for session {session_id}")
    except Exception as e:
        logger.error(f"Error updating session feedback for session {session_id}: {e}", exc_info=True)
        # Don't raise - feedback was already recorded, this is just aggregation


@router.post("/feedback", response_model=dict)
async def submit_feedback(request: FeedbackRequest):
    """Submit feedback for a chat message."""
    if not railway_db or not hasattr(railway_db, '_pool') or railway_db._pool is None:
        raise HTTPException(status_code=503, detail="Database not initialized")
    
    try:
        async with railway_db.acquire() as conn:
            # Insert feedback
            await conn.execute(
                """
                INSERT INTO chat_feedback (message_id, session_id, feedback_type)
                VALUES ($1, $2, $3)
                """,
                request.message_id, request.session_id, request.feedback
            )
            
            # Update session-level feedback aggregation
            await update_session_feedback(request.session_id, conn)
            
            logger.info(f"Feedback recorded: {request.feedback} for message {request.message_id}")
            
            return {
                "success": True,
                "message": "Feedback recorded"
            }
    except Exception as e:
        logger.error(f"Error recording feedback: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error recording feedback: {str(e)}")

