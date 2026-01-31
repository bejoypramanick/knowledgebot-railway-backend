"""
Feedback Service Layer
Provides business logic for feedback management operations
"""
from typing import Any, Dict, Optional

from configuration.core.logging_config import get_railway_logger

from ..dao.feedback_dao import FeedbackDAO

logger = get_railway_logger(__name__)

class FeedbackService:
    """Service layer for feedback management"""
    
    def __init__(self):
        self.feedback_dao = FeedbackDAO()  # Service manages its own DAO
    
    async def submit_feedback(self, message_id: str, session_id: str, feedback: str, user_email: Optional[str] = None) -> Dict[str, Any]:
        """Submit feedback for a message"""
        try:
            await self.feedback_dao.create_feedback(message_id, session_id, feedback, user_email)
            logger.info(f"Feedback submitted for message {message_id}")
            return {"success": True, "message": "Feedback submitted successfully"}
        except Exception as e:
            logger.error(f"Error submitting feedback: {e}")
            raise
    
    async def get_all_feedback(self) -> List[Dict[str, Any]]:
        """Get all feedback"""
        try:
            feedback_list = await self.feedback_dao.get_all_feedback()
            return feedback_list
        except Exception as e:
            logger.error(f"Error getting all feedback: {e}")
            raise
