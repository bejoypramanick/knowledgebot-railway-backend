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
                        COUNT(*) as total_feedback,
                        COUNT(CASE WHEN feedback = 'positive' THEN 1 END) as positive_feedback,
                        COUNT(CASE WHEN feedback = 'negative' THEN 1 END) as negative_feedback,
                        ROUND(
                            COUNT(CASE WHEN feedback = 'positive' THEN 1 END) * 100.0 / 
                            NULLIF(COUNT(*), 0), 2
                        ) as positive_percentage
                    FROM message_feedback 
                    WHERE created_at >= NOW() - INTERVAL $1 day
                """
                # Use parameterized query to prevent SQL injection
                result = await fetchrow_with_logging(conn, query, days, operation="GET_FEEDBACK_STATS")
                logger.info(f"🔍 DEBUG: get_feedback_stats completed")
                return dict(result) if result else {}
        except Exception as e:
            logger.error(f"Error getting feedback stats: {e}")
            return {}

    async def get_feedback_by_session(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all feedback for a specific session."""
        try:
            logger.info(f"🔍 DEBUG: get_feedback_by_session called with session_id={session_id}")
            async with get_db_connection() as conn:
                query = """
                    SELECT message_id, feedback, user_email, created_at
                    FROM message_feedback 
                    WHERE session_id = $1
                    ORDER BY created_at DESC
                """
                result = await fetch_with_logging(conn, query, session_id, operation="GET_FEEDBACK_BY_SESSION")
                logger.info(f"🔍 DEBUG: get_feedback_by_session completed")
                return result
        except Exception as e:
            logger.error(f"Error getting feedback by session: {e}")
            return []

    async def get_daily_feedback_trend(self, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily feedback trend for the last N days."""
        try:
            logger.info(f"🔍 DEBUG: get_daily_feedback_trend called with days={days}")
            async with get_db_connection() as conn:
                query = """
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
                    WHERE created_at >= NOW() - INTERVAL $1 day
                    GROUP BY DATE(created_at)
                    ORDER BY date DESC
                """
                result = await fetch_with_logging(conn, query, days, operation="GET_DAILY_FEEDBACK_TREND")
                logger.info(f"🔍 DEBUG: get_daily_feedback_trend completed")
                return result
        except Exception as e:
            logger.error(f"Error getting daily feedback trend: {e}")
            return []
