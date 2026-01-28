"""
Feedback Service Layer
Provides business logic for feedback management operations
"""
import logging
from typing import List, Optional, Dict, Any
from ..dao.feedback_dao import FeedbackDAO

logger = logging.getLogger(__name__)

class FeedbackService:
    """Service layer for feedback management"""
    
    def __init__(self, connection):
        self.feedback_dao = FeedbackDAO(connection)
    
    async def submit_feedback(self, message_id: str, session_id: str, feedback: str, user_email: Optional[str] = None) -> Dict[str, Any]:
        """Submit feedback for a message"""
        try:
            await self.feedback_dao.create_feedback(message_id, session_id, feedback, user_email)
            logger.info(f"Feedback submitted for message {message_id}")
            return {"success": True, "message": "Feedback submitted successfully"}
        except Exception as e:
            logger.error(f"Error submitting feedback: {e}")
            raise
    
    async def get_feedback_stats(self) -> Dict[str, Any]:
        """Get feedback statistics"""
        try:
            stats = await self.feedback_dao.get_feedback_stats()
            return stats
        except Exception as e:
            logger.error(f"Error fetching feedback stats: {e}")
            raise
