from typing import Any, Dict, List, Optional

from configuration.core.db import get_db_connection
from configuration.core.db_logger import execute_with_logging
from configuration.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class FeedbackDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def verify_message_session(self, message_id: str, session_id: str) -> Optional[str]:
        """Verify that a message belongs to a specific session."""
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(
                    """
                    SELECT user_email 
                    FROM chat_messages 
                    WHERE message_id = $1 AND session_id = $2
                    LIMIT 1
                    """,
                    message_id, session_id
                )
                return result["user_email"] if result else None
        except Exception as e:
            logger.error(f"Error verifying message session: {e}")
            return None

    async def submit_feedback(self, message_id: str, session_id: str, feedback: str, user_email: str):
        """Submit feedback for a chat message."""
        try:
            logger.info(f"🔍 DEBUG: submit_feedback called with message_id={message_id}, session_id={session_id}, feedback={feedback}, user_email={user_email}")
            async with get_db_connection() as conn:
                query = """
                    INSERT INTO message_feedback 
                    (message_id, session_id, feedback, user_email, created_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    ON CONFLICT (message_id) DO UPDATE SET
                    feedback = EXCLUDED.feedback,
                    user_email = EXCLUDED.user_email,
                    created_at = EXCLUDED.created_at
                """
                params = [message_id, session_id, feedback, user_email]
                logger.info(f"🔍 DEBUG: About to call execute_with_logging")
                await execute_with_logging(conn, query, *params, operation="SUBMIT_FEEDBACK")
                logger.info(f"🔍 DEBUG: execute_with_logging completed")
        except Exception as e:
            logger.error(f"Error submitting feedback: {e}")
            raise

    async def get_feedback_stats(self, days: int = 30) -> Dict[str, Any]:
        """Get feedback statistics for the last N days."""
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(
                    """
                    SELECT 
                        COUNT(*) as total_feedback,
                        COUNT(CASE WHEN feedback = 'positive' THEN 1 END) as positive_feedback,
                        COUNT(CASE WHEN feedback = 'negative' THEN 1 END) as negative_feedback,
                        ROUND(
                            COUNT(CASE WHEN feedback = 'positive' THEN 1 END) * 100.0 / 
                            NULLIF(COUNT(*), 0), 2
                        ) as positive_percentage
                    FROM message_feedback 
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                    """ % days
                )
                return dict(result) if result else {}
        except Exception as e:
            logger.error(f"Error getting feedback stats: {e}")
            return {}

    async def get_feedback_by_session(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all feedback for a specific session."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetch(
                    """
                    SELECT message_id, feedback, user_email, created_at
                    FROM message_feedback 
                    WHERE session_id = $1
                    ORDER BY created_at DESC
                    """,
                    session_id
                )
        except Exception as e:
            logger.error(f"Error getting feedback by session: {e}")
            return []

    async def get_daily_feedback_trend(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily feedback trend for the last N days."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetch(
                    """
                    SELECT 
                        DATE(created_at) as date,
                        COUNT(*) as total_feedback,
                        COUNT(CASE WHEN feedback = 'positive' THEN 1 END) as positive_feedback,
                        COUNT(CASE WHEN feedback = 'negative' THEN 1 END) as negative_feedback,
                        ROUND(
                            COUNT(CASE WHEN feedback = 'positive' THEN 1 END) * 100.0 / 
                            NULLIF(COUNT(*), 0), 2
                        ) as positive_percentage
                    FROM message_feedback 
                    WHERE created_at >= NOW() - INTERVAL '%s days'
                    GROUP BY DATE(created_at)
                    ORDER BY date DESC
                    """ % days
                )
        except Exception as e:
            logger.error(f"Error getting daily feedback trend: {e}")
            return []
