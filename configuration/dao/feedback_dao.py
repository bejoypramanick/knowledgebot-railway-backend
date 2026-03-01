"""
Feedback Data Access Object for Configuration Service
Handles database operations for user feedback
"""
from typing import Dict, List, Any, Optional

from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("feedback_dao", "configuration")

class FeedbackDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def create_feedback(self, session_id: str, feedback_type: str, user_role_id: Optional[int] = None):
        """Submit feedback for a chat session.

        Args:
            session_id: The session ID to provide feedback for
            feedback_type: Either 'positive' or 'negative'
            user_role_id: Optional user role ID for audit trail
        """
        # Validate feedback_type
        if feedback_type not in ['positive', 'negative']:
            raise ValueError(f"Invalid feedback_type: {feedback_type}. Must be 'positive' or 'negative'")

        query = """
            UPDATE chat_sessions
            SET feedback_type = $1, feedback_provided_at = NOW(), feedback_user_role_id = $2
            WHERE session_id = $3
        """
        params = {"feedback_type": feedback_type, "user_role_id": user_role_id, "session_id": session_id}

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, feedback_type, user_role_id, session_id)
                logger.log_db_query(query, params, result)
                if result == "UPDATE 0":
                    raise ValueError(f"Session not found: {session_id}")
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def get_all_feedback(self) -> List[Dict[str, Any]]:
        """Get all feedback (sessions with feedback provided)."""
        query = """
            SELECT session_id, feedback_type, feedback_provided_at, feedback_user_role_id
            FROM chat_sessions
            WHERE feedback_type IS NOT NULL
            ORDER BY feedback_provided_at DESC
        """

        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                records = await conn.fetch(query)
                logger.log_db_query(query, None, records)
                return records
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            raise

    async def get_feedback_counts_by_sessions(self, session_ids: List[str]) -> Dict[str, Dict[str, int]]:
        """Get feedback counts (positive and negative) for multiple sessions.

        Args:
            session_ids: List of session IDs to get feedback counts for

        Returns:
            Dictionary with session_id as key and {positive: count, negative: count} as value
        """
        if not session_ids:
            return {}

        query = """
            SELECT
                session_id,
                feedback_type,
                COUNT(*) as count
            FROM chat_sessions
            WHERE session_id = ANY($1::text[]) AND feedback_type IS NOT NULL
            GROUP BY session_id, feedback_type
        """

        params = {"session_ids": session_ids}

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                records = await conn.fetch(query, session_ids)
                logger.log_db_query(query, params, records)

                # Transform results into expected format
                result = {}
                for record in records:
                    session_id = str(record['session_id'])
                    feedback_type = record['feedback_type']
                    count = record['count']

                    if session_id not in result:
                        result[session_id] = {'positive': 0, 'negative': 0}

                    # Map feedback types to positive/negative
                    if feedback_type == 'positive':
                        result[session_id]['positive'] = count
                    elif feedback_type == 'negative':
                        result[session_id]['negative'] = count

                # Ensure all session IDs are in result with zero counts if no feedback
                for session_id in session_ids:
                    if session_id not in result:
                        result[session_id] = {'positive': 0, 'negative': 0}

                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise
