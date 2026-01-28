import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class FeedbackDAO:
    def __init__(self, connection):
        self.conn = connection

    async def verify_message_session(self, message_id: str, session_id: str) -> Optional[str]:
        """Verify that a message belongs to a specific session."""
        return await self.conn.fetchval(
            "SELECT session_id FROM chat_messages WHERE id = $1",
            message_id
        )

    async def insert_feedback(self, message_id: str, session_id: str, feedback: str) -> None:
        """Insert feedback for a message."""
        await self.conn.execute(
            """
            INSERT INTO message_feedback (message_id, session_id, feedback, created_at)
            VALUES ($1, $2, $3, NOW())
            ON CONFLICT (message_id) 
            DO UPDATE SET 
                feedback = EXCLUDED.feedback,
                created_at = EXCLUDED.created_at
            """,
            message_id, session_id, feedback
        )

    async def get_message_feedback(self, message_id: str) -> Optional[Dict[str, Any]]:
        """Get feedback for a specific message."""
        return await self.conn.fetchrow(
            """
            SELECT feedback, created_at 
            FROM message_feedback 
            WHERE message_id = $1
            """,
            message_id
        )
