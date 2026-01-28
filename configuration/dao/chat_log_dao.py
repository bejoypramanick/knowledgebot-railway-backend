from shared.logging_config import get_railway_logger
import logging
from typing import Optional, Dict, Any, List
from shared.db import get_db_connection

logger = get_railway_logger(__name__)

class ChatLogDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_agent_online_status(self, agent_email: str) -> bool:
        """Check if an agent is online by checking their last activity timestamp."""
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(
                    """
                    SELECT 1 
                    FROM human_agents ha
                    WHERE ha.email = $1 
                      AND ha.is_active = true
                      AND ha.last_activity >= NOW() - INTERVAL '5 minutes'
                    """,
                    agent_email
                )
                return result is not None
        except Exception as e:
            logger.error(f"Error checking agent online status: {e}")
            return False

    async def log_chat_message(self, session_id: str, message_id: str, sender_type: str, 
                              sender_email: str, message_content: str, metadata: Optional[Dict] = None):
        """Log a chat message to the database."""
        try:
            async with get_db_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO chat_messages 
                    (session_id, message_id, sender_type, sender_email, message_content, metadata, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, NOW())
                    """,
                    session_id, message_id, sender_type, sender_email, message_content, metadata
                )
        except Exception as e:
            logger.error(f"Error logging chat message: {e}")
            raise

    async def get_chat_history(self, session_id: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get chat history for a session."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetch(
                    """
                    SELECT message_id, sender_type, sender_email, message_content, 
                           metadata, created_at
                    FROM chat_messages 
                    WHERE session_id = $1
                    ORDER BY created_at ASC
                    LIMIT $2
                    """,
                    session_id, limit
                )
        except Exception as e:
            logger.error(f"Error getting chat history: {e}")
            return []

    async def create_chat_session(self, session_id: str, user_email: str, metadata: Optional[Dict] = None):
        """Create a new chat session."""
        try:
            async with get_db_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO chat_sessions 
                    (session_id, user_email, metadata, created_at)
                    VALUES ($1, $2, $3, NOW())
                    """,
                    session_id, user_email, metadata
                )
        except Exception as e:
            logger.error(f"Error creating chat session: {e}")
            raise

    async def update_session_activity(self, session_id: str):
        """Update the last activity timestamp for a session."""
        try:
            async with get_db_connection() as conn:
                await conn.execute(
                    """
                    UPDATE chat_sessions 
                    SET last_activity = NOW()
                    WHERE session_id = $1
                    """,
                    session_id
                )
        except Exception as e:
            logger.error(f"Error updating session activity: {e}")
            raise

    async def get_active_sessions(self, limit: int = 100) -> List[Dict[str, Any]]:
        """Get active chat sessions."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetch(
                    """
                    SELECT session_id, user_email, created_at, last_activity, metadata
                    FROM chat_sessions 
                    WHERE last_activity >= NOW() - INTERVAL '1 hour'
                    ORDER BY last_activity DESC
                    LIMIT $1
                    """,
                    limit
                )
        except Exception as e:
            logger.error(f"Error getting active sessions: {e}")
            return []

    async def assign_agent_to_session(self, session_id: str, agent_email: str, assigned_by: str):
        """Assign a human agent to a chat session."""
        try:
            async with get_db_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO agent_session_assignments 
                    (session_id, agent_email, assigned_by, assigned_at, status)
                    VALUES ($1, $2, $3, NOW(), 'active')
                    ON CONFLICT (session_id) DO UPDATE SET
                    agent_email = EXCLUDED.agent_email,
                    assigned_by = EXCLUDED.assigned_by,
                    assigned_at = EXCLUDED.assigned_at,
                    status = EXCLUDED.status
                    """,
                    session_id, agent_email, assigned_by
                )
        except Exception as e:
            logger.error(f"Error assigning agent to session: {e}")
            raise

    async def get_session_assignment(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get the current agent assignment for a session."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchrow(
                    """
                    SELECT agent_email, assigned_by, assigned_at, status
                    FROM agent_session_assignments 
                    WHERE session_id = $1 AND status = 'active'
                    ORDER BY assigned_at DESC
                    LIMIT 1
                    """,
                    session_id
                )
        except Exception as e:
            logger.error(f"Error getting session assignment: {e}")
            return None
