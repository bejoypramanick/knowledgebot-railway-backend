"""
Feedback Data Access Object for Configuration Service
Handles database operations for user feedback management
"""
from typing import Dict, List, Any, Optional

from configuration.core.db import get_db_connection
from configuration.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class FeedbackDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def create_feedback(self, message_id: str, session_id: str, feedback: str, user_email: Optional[str] = None):
        """Submit feedback for a chat message."""
        try:
            async with get_db_connection() as conn:
                await conn.execute("""
                    INSERT INTO feedback (message_id, session_id, feedback, user_email, created_at)
                    VALUES ($1, $2, $3, $4, NOW())
                """, message_id, session_id, feedback, user_email)
                logger.info(f"Feedback submitted for message {message_id}")
        except Exception as e:
            logger.error(f"Error submitting feedback: {e}")
            raise

    async def get_all_feedback(self) -> List[Dict[str, Any]]:
        """Get all feedback."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetch("""
                    SELECT id, message_id, session_id, feedback, user_email, created_at
                    FROM feedback
                    ORDER BY created_at DESC
                """)
        except Exception as e:
            logger.error(f"Error getting all feedback: {e}")
            raise
