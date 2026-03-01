"""
Feedback Service Layer
Provides business logic for feedback management operations
"""
from typing import Any, Dict, List, Optional

from shared.otel_logger import get_otel_logger

from ..dao.feedback_dao import FeedbackDAO

logger = get_otel_logger("feedback_service", "configuration")

class FeedbackService:
    """Service layer for feedback management"""
    
    def __init__(self):
        self.feedback_dao = FeedbackDAO()  # Service manages its own DAO
    
    async def submit_feedback(self, message_id: str, session_id: str, feedback_type: str, user_role_id: Optional[int] = None) -> Dict[str, Any]:
        """Submit feedback for a message"""
        try:
            await self.feedback_dao.create_feedback(message_id, session_id, feedback_type, user_role_id)
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

    async def get_feedback_counts_by_sessions(self, session_ids: List[str]) -> Dict[str, Dict[str, int]]:
        """Get feedback counts for multiple sessions

        Args:
            session_ids: List of session IDs to get feedback for

        Returns:
            Dictionary with session_id as key and {positive: count, negative: count} as value
        """
        try:
            logger.info(f"Getting feedback counts for sessions: {session_ids}")
            result = await self.feedback_dao.get_feedback_counts_by_sessions(session_ids)
            logger.info(f"Feedback counts retrieved: {result}")
            return result
        except Exception as e:
            logger.error(f"Error getting feedback counts by sessions: {e}")
            raise
