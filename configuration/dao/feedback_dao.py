"""
Feedback Data Access Object for Configuration Service
Handles database operations for user feedback
"""
from typing import Dict, List, Any, Optional

from configuration.core.db import get_db_connection
from configuration.core.otel_logger import get_otel_logger

logger = get_otel_logger("feedback_dao", "configuration")

class FeedbackDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def create_feedback(self, message_id: str, session_id: str, feedback: str, user_email: Optional[str] = None):
        """Submit feedback for a chat message."""
        query = """
            INSERT INTO feedback (message_id, session_id, feedback, user_email, created_at)
            VALUES ($1, $2, $3, $4, NOW())
        """
        params = {"message_id": message_id, "session_id": session_id, "feedback": feedback, "user_email": user_email}
        
        try:
            async with get_db_connection() as conn:
                await conn.execute(query, message_id, session_id, feedback, user_email)
                logger.info(f"🔍 [DB QUERY] create_feedback: {query.strip()} | PARAMS: {params}")
                logger.info(f"Feedback submitted for message {message_id}")
        except Exception as e:
            logger.error(f"❌ [DB ERROR] create_feedback: {e}")
            raise

    async def get_all_feedback(self) -> List[Dict[str, Any]]:
        """Get all feedback."""
        query = """
            SELECT id, message_id, session_id, feedback, user_email, created_at
            FROM feedback
            ORDER BY created_at DESC
        """
        
        try:
            async with get_db_connection() as conn:
                records = await conn.fetch(query)
                logger.info(f"🔍 [DB QUERY] get_all_feedback: {query.strip()} | FOUND: {len(records)} records")
                return records
        except Exception as e:
            logger.error(f"❌ [DB ERROR] get_all_feedback: {e}")
            raise
