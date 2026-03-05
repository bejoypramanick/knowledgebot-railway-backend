"""
Feedback Data Access Object for Configuration Service
Handles database operations for user feedback
"""
from typing import Dict, List, Any, Optional

from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("feedback_dao", "configuration")

class FeedbackDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def create_feedback(self, session_id: str, feedback_type: str):
        """Submit feedback for a chat session.

        Args:
            session_id: The session ID to provide feedback for
            feedback_type: Either 'positive' or 'negative'
        """
        # Validate feedback_type
        if feedback_type not in ['positive', 'negative']:
            raise ValueError(f"Invalid feedback_type: {feedback_type}. Must be 'positive' or 'negative'")

        query = """
            UPDATE chat_sessions
            SET feedback_type = :feedback_type, feedback_provided_at = NOW()
            WHERE session_id = :session_id
        """
        params = {"feedback_type": feedback_type, "session_id": session_id}

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
                if result.rowcount == 0:
                    raise ValueError(f"Session not found: {session_id}")
                return True
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
            async with get_db_session() as session:
                result = await session.execute(text(query))
                records = result.fetchall()
                logger.log_db_query(query, None, records)
                return [dict(row._mapping) for row in records]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            raise

    async def get_feedback_counts_by_sessions(self, session_ids: List[str]) -> Dict[str, Dict[str, int]]:
        """Get feedback for multiple sessions.

        Args:
            session_ids: List of session IDs (UUID strings) to get feedback for

        Returns:
            Dictionary with session_id as key and {positive: count, negative: count} as value
            (count is 1 or 0 since each session has only one feedback)
        """
        if not session_ids:
            return {}

        # Build dynamic IN clause for asyncpg compatibility
        placeholders = ",".join([f":id_{i}" for i in range(len(session_ids))])
        params = {f"id_{i}": sid for i, sid in enumerate(session_ids)}

        # Initialize result with zero counts for all sessions
        result_dict = {session_id: {'positive': 0, 'negative': 0} for session_id in session_ids}

        query = f"""
            SELECT
                session_id,
                feedback_type
            FROM chat_sessions
            WHERE session_id IN ({placeholders})
        """

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                records = result.fetchall()
                logger.log_db_query(query, params, records)

                # Transform results into expected format
                for record in records:
                    session_id = str(record['session_id'])
                    feedback_type = record.get('feedback_type')

                    if session_id in result_dict:
                        # Update with actual feedback (1 or 0 for each type)
                        result_dict[session_id]['positive'] = 1 if feedback_type == 'positive' else 0
                        result_dict[session_id]['negative'] = 1 if feedback_type == 'negative' else 0

                return result_dict
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            # Return zero counts for all sessions if query fails
            logger.warning(f"Could not retrieve feedback counts (feedback_type column may not exist): {e}")
            return result_dict
