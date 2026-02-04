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

    async def create_feedback(self, message_id: str, session_id: str, feedback_type: str, user_role_id: Optional[int] = None):
        """Submit feedback for a chat message."""
        query = """
            INSERT INTO chat_feedback (message_id, session_id, feedback_type, user_role_id, created_at)
            VALUES ($1, $2, $3, $4, NOW())
        """
        params = {"message_id": message_id, "session_id": session_id, "feedback_type": feedback_type, "user_role_id": user_role_id}
        
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, message_id, session_id, feedback_type, user_role_id)
                logger.log_db_query(query, params, result)
                logger.info(f"Feedback submitted for message {message_id}")
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def get_all_feedback(self) -> List[Dict[str, Any]]:
        """Get all feedback."""
        query = """
            SELECT cf.id, cf.message_id, cf.session_id, cf.feedback_type, cf.user_role_id, 
                   cf.created_at, cf.updated_at,
                   u.email as user_email, r.role_name
            FROM chat_feedback cf
            LEFT JOIN user_role_mapping urm ON cf.user_role_id = urm.user_role_id
            LEFT JOIN users u ON urm.user_id = u.id
            LEFT JOIN roles r ON urm.role_id = r.id
            ORDER BY cf.created_at DESC
        """
        
        try:
            async with get_db_connection() as conn:
                records = await conn.fetch(query)
                logger.log_db_query(query, None, records)
                return records
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            raise
