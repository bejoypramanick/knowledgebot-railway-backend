from typing import Any, Dict, List, Optional

from api_gateway.core.db import get_db_connection
from api_gateway.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class ChatDAO:
    """Shared DAO for chat-related operations across all services."""
    
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_sessions_for_agent(self, agent_email: str, archive_status: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        """Get chat sessions assigned to a specific agent."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetch(
                    """
                    SELECT cs.id, cs.session_id, cs.metadata, cs.created_at, cs.updated_at,
                           sa.agent_email, sa.status as assignment_status, sa.assigned_at
                    FROM chat_sessions cs
                    LEFT JOIN agent_session_assignments sa ON cs.id = sa.session_id
                    WHERE sa.agent_email = $1 
                      AND sa.status = 'active'
                      AND ($2 = 'active' OR cs.status = $2)
                    ORDER BY cs.updated_at DESC
                    LIMIT $3 OFFSET $4
                    """,
                    agent_email, archive_status, limit, offset
                )
        except Exception as e:
            logger.error(f"Error getting sessions for agent {agent_email}: {e}")
            return []

    async def count_sessions_for_agent(self, agent_email: str, archive_status: str) -> int:
        """Count chat sessions assigned to a specific agent."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM chat_sessions cs
                    LEFT JOIN agent_session_assignments sa ON cs.id = sa.session_id
                    WHERE sa.agent_email = $1 
                      AND sa.status = 'active'
                      AND ($2 = 'active' OR cs.status = $2)
                    """,
                    agent_email, archive_status
                ) or 0
        except Exception as e:
            logger.error(f"Error counting sessions for agent {agent_email}: {e}")
            return 0

    async def get_all_sessions(self, archive_status: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        """Get all chat sessions."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetch(
                    """
                    SELECT cs.id, cs.session_id, cs.metadata, cs.created_at, cs.updated_at,
                           sa.agent_email, sa.status as assignment_status, sa.assigned_at
                    FROM chat_sessions cs
                    LEFT JOIN agent_session_assignments sa ON cs.id = sa.session_id
                    WHERE ($1 = 'active' OR cs.status = $1)
                    ORDER BY cs.updated_at DESC
                    LIMIT $2 OFFSET $3
                    """,
                    archive_status, limit, offset
                )
        except Exception as e:
            logger.error(f"Error getting all sessions: {e}")
            return []

    async def count_all_sessions(self, archive_status: str) -> int:
        """Count all chat sessions."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchval(
                    """
                    SELECT COUNT(*)
                    FROM chat_sessions cs
                    WHERE ($1 = 'active' OR cs.status = $1)
                    """,
                    archive_status
                ) or 0
        except Exception as e:
            logger.error(f"Error counting all sessions: {e}")
            return 0

    async def get_messages_for_sessions(self, session_db_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
        """Get messages for multiple sessions, organized by session ID."""
        try:
            async with get_db_connection() as conn:
                if not session_db_ids:
                    return {}
                
                messages = await conn.fetch(
                    """
                    SELECT id, session_id, content, role, created_at
                    FROM chat_messages
                    WHERE session_id = ANY($1)
                    ORDER BY created_at ASC
                    """,
                    session_db_ids
                )
                
                # Organize messages by session_id
                messages_by_session = {}
                for msg in messages:
                    session_id = msg['session_id']
                    if session_id not in messages_by_session:
                        messages_by_session[session_id] = []
                    messages_by_session[session_id].append(dict(msg))
                
                return messages_by_session
        except Exception as e:
            logger.error(f"Error getting messages for sessions: {e}")
            return {}

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
                    SELECT content, role, created_at
                    FROM chat_messages
                    WHERE session_id = $1
                    ORDER BY created_at DESC
                    LIMIT $2
                    """,
                    session_id, limit
                )
        except Exception as e:
            logger.error(f"Error getting chat history: {e}")
            return []

    async def get_session_db_id(self, session_id: str) -> Optional[int]:
        """Get database ID for a session."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchval(
                    "SELECT id FROM chat_sessions WHERE session_id = $1",
                    session_id
                )
        except Exception as e:
            logger.error(f"Error getting session DB ID: {e}")
            return None

    async def create_chat_session(self, session_id: str, metadata: Dict[str, Any]) -> int:
        """Create a new chat session."""
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(
                    """
                    INSERT INTO chat_sessions (session_id, metadata, created_at, updated_at)
                    VALUES ($1, $2, NOW(), NOW())
                    RETURNING id
                    """,
                    session_id, metadata
                )
                return result['id']
        except Exception as e:
            logger.error(f"Error creating chat session: {e}")
            raise

    async def update_chat_session_metadata(self, session_db_id: int, metadata: Dict[str, Any]):
        """Update chat session metadata."""
        try:
            async with get_db_connection() as conn:
                await conn.execute(
                    """
                    UPDATE chat_sessions 
                    SET metadata = $1, updated_at = NOW()
                    WHERE id = $2
                    """,
                    metadata, session_db_id
                )
        except Exception as e:
            logger.error(f"Error updating session metadata: {e}")
            raise

    async def get_assignee_type(self, agent_email: str) -> str:
        """Get the type of assignee (admin or human_agent)."""
        try:
            async with get_db_connection() as conn:
                # Check if admin first
                admin_check = await conn.fetchval(
                    "SELECT id FROM admins WHERE email = $1 AND status = 'active'",
                    agent_email
                )
                if admin_check:
                    return "admin"
                
                # Then check if human agent
                agent_check = await conn.fetchval(
                    "SELECT id FROM human_agents WHERE email = $1 AND removed_at IS NULL",
                    agent_email
                )
                if agent_check:
                    return "human_agent"
                
                return "unknown"
        except Exception as e:
            logger.error(f"Error getting assignee type: {e}")
            return "unknown"

    async def get_session_assignment(self, session_db_id: int) -> Optional[Dict[str, Any]]:
        """Get current assignment for a session."""
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
                    session_db_id
                )
        except Exception as e:
            logger.error(f"Error getting session assignment: {e}")
            return None

    async def create_session_assignment(self, session_db_id: int, agent_email: str, assignee_type: str, status: str = 'active'):
        """Create a new session assignment."""
        try:
            async with get_db_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO agent_session_assignments 
                    (session_id, agent_email, assignee_type, status, assigned_at)
                    VALUES ($1, $2, $3, $4, NOW())
                    """,
                    session_db_id, agent_email, assignee_type, status
                )
        except Exception as e:
            logger.error(f"Error creating session assignment: {e}")
            raise

    async def update_session_assignment(self, session_db_id: int, agent_email: str, assignee_type: str):
        """Update an existing session assignment."""
        try:
            async with get_db_connection() as conn:
                await conn.execute(
                    """
                    UPDATE agent_session_assignments 
                    SET agent_email = $1, assignee_type = $2, assigned_at = NOW()
                    WHERE session_id = $3 AND status = 'active'
                    """,
                    agent_email, assignee_type, session_db_id
                )
        except Exception as e:
            logger.error(f"Error updating session assignment: {e}")
            raise

    async def update_last_activity(self, session_db_id: int):
        """Update the last activity timestamp for a session."""
        try:
            async with get_db_connection() as conn:
                await conn.execute(
                    "UPDATE chat_sessions SET updated_at = NOW() WHERE id = $1",
                    session_db_id
                )
        except Exception as e:
            logger.error(f"Error updating last activity: {e}")
            raise

    async def get_agent_chat_count(self, agent_email: str) -> int:
        """Get number of active chats for an agent."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchval(
                    """
                    SELECT COUNT(*) 
                    FROM agent_session_assignments 
                    WHERE agent_email = $1 AND status = 'active'
                    """,
                    agent_email
                ) or 0
        except Exception as e:
            logger.error(f"Error getting agent chat count: {e}")
            return 0
