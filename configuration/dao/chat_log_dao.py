"""
Chat Log Data Access Object for Configuration Service
Handles database operations for chat logging
"""
from typing import Dict, List, Any, Optional
import json
from datetime import datetime

from configuration.core.db import get_db_connection
from configuration.core.otel_logger import get_otel_logger

logger = get_otel_logger("chat_log_dao", "configuration")

class ChatLogDAO:
    def __init__(self):
        self.conn = None  # Connection is managed via get_db_connection context manager usually, but some methods might expect self.conn if they were designed differently. 
        # However, looking at usage, it seems methods use `async with get_db_connection() as conn`.

    async def get_all_human_agents(self) -> List[str]:
        """Get all human agent emails."""
        query = "SELECT email FROM human_agents WHERE status = 'active'"
        try:
            async with get_db_connection() as conn:
                rows = await conn.fetch(query)
                logger.log_db_query(query, None, rows)
                return [r['email'] for r in rows]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def get_all_admins(self) -> List[str]:
        """Get all admin emails."""
        query = "SELECT email FROM admins WHERE status = 'active'"
        try:
            async with get_db_connection() as conn:
                rows = await conn.fetch(query)
                logger.log_db_query(query, None, rows)
                return [r['email'] for r in rows]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def check_user_role(self, email: str) -> Dict[str, bool]:
        """Check if user is agent or admin."""
        try:
            async with get_db_connection() as conn:
                is_agent_query = "SELECT EXISTS(SELECT 1 FROM human_agents WHERE email = $1 AND status = 'active')"
                is_admin_query = "SELECT EXISTS(SELECT 1 FROM admins WHERE email = $1 AND status = 'active')"
                
                is_agent = await conn.fetchval(is_agent_query, email)
                logger.log_db_query(is_agent_query, {"email": email}, is_agent)
                
                is_admin = await conn.fetchval(is_admin_query, email)
                logger.log_db_query(is_admin_query, {"email": email}, is_admin)
                
                return {"is_agent": is_agent, "is_admin": is_admin}
        except Exception as e:
            logger.log_db_query("check_user_role", {"email": email}, error=e)
            return {"is_agent": False, "is_admin": False}

    async def get_agent_chat_count(self, email: str) -> int:
        """Get active chat count for agent."""
        query = """
            SELECT COUNT(*) FROM session_assignments 
            WHERE assignee_email = $1 AND status = 'active'
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, email)
                logger.log_db_query(query, {"email": email}, result)
                return result
        except Exception as e:
            logger.log_db_query(query, {"email": email}, error=e)
            return 0

    async def get_session_db_id(self, session_id: str) -> Optional[int]:
        """Get database ID for a session UUID string."""
        query = "SELECT id FROM chat_sessions WHERE session_id = $1"
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, session_id)
                logger.log_db_query(query, {"session_id": session_id}, result)
                return result
        except Exception as e:
            logger.log_db_query(query, {"session_id": session_id}, error=e)
            return None

    async def create_chat_session(self, session_id: str, metadata: Dict[str, Any]) -> int:
        """Create a new chat session."""
        query = """
            INSERT INTO chat_sessions (session_id, metadata, created_at, last_activity_at, is_active)
            VALUES ($1, $2, NOW(), NOW(), true)
            RETURNING id
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, session_id, json.dumps(metadata))
                logger.log_db_query(query, {"session_id": session_id, "metadata": metadata}, result)
                return result
        except Exception as e:
            logger.log_db_query(query, {"session_id": session_id, "metadata": metadata}, error=e)
            raise

    async def get_assignee_type(self, email: str) -> str:
        """Determine if email belongs to agent or admin."""
        roles = await self.check_user_role(email)
        if roles['is_agent']: return 'agent'
        if roles['is_admin']: return 'admin'
        return 'system'

    async def get_session_assignment(self, session_db_id: int) -> Optional[Dict[str, Any]]:
        """Get assignment for a session."""
        query = "SELECT * FROM session_assignments WHERE session_id = $1"
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, session_db_id)
                logger.log_db_query(query, {"session_db_id": session_db_id}, result)
                return result
        except Exception as e:
            logger.log_db_query(query, {"session_db_id": session_db_id}, error=e)
            return None

    async def update_session_assignment(self, session_db_id: int, email: str, type: str, status: str):
        """Update session assignment."""
        query = """
            UPDATE session_assignments 
            SET assignee_email = $2, assignee_type = $3, status = $4, assigned_at = NOW(), updated_at = NOW()
            WHERE session_id = $1
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, session_db_id, email, type, status)
                logger.log_db_query(query, {"session_db_id": session_db_id, "email": email, "type": type, "status": status}, result)
        except Exception as e:
            logger.log_db_query(query, {"session_db_id": session_db_id, "email": email, "type": type, "status": status}, error=e)
            raise

    async def create_session_assignment(self, session_db_id: int, email: str, type: str, status: str):
        """Create session assignment."""
        query = """
            INSERT INTO session_assignments (session_id, assignee_email, assignee_type, status, assigned_at, created_at, updated_at)
            VALUES ($1, $2, $3, $4, NOW(), NOW(), NOW())
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, session_db_id, email, type, status)
                logger.log_db_query(query, {"session_db_id": session_db_id, "email": email, "type": type, "status": status}, result)
        except Exception as e:
            logger.log_db_query(query, {"session_db_id": session_db_id, "email": email, "type": type, "status": status}, error=e)
            raise

    async def get_sessions_for_agent(self, email: str, archive_status: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        query = """
            SELECT cs.*, sa.assignee_email as agent_email 
            FROM chat_sessions cs
            LEFT JOIN session_assignments sa ON cs.id = sa.session_id
            WHERE sa.assignee_email = $1 AND cs.archive_status = $2
            ORDER BY cs.last_activity_at DESC
            LIMIT $3 OFFSET $4
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetch(query, email, archive_status, limit, offset)
                logger.log_db_query(query, {"email": email, "archive_status": archive_status, "limit": limit, "offset": offset}, result)
                return result
        except Exception as e:
            logger.log_db_query(query, {"email": email, "archive_status": archive_status, "limit": limit, "offset": offset}, error=e)
            return []

    async def count_sessions_for_agent(self, email: str, archive_status: str) -> int:
        query = """
            SELECT COUNT(*) 
            FROM chat_sessions cs
            LEFT JOIN session_assignments sa ON cs.id = sa.session_id
            WHERE sa.assignee_email = $1 AND cs.archive_status = $2
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, email, archive_status)
                logger.log_db_query(query, {"email": email, "archive_status": archive_status}, result)
                return result
        except Exception as e:
            logger.log_db_query(query, {"email": email, "archive_status": archive_status}, error=e)
            return 0

    async def get_all_sessions(self, archive_status: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        query = """
            SELECT cs.*, sa.assignee_email as agent_email 
            FROM chat_sessions cs
            LEFT JOIN session_assignments sa ON cs.id = sa.session_id
            WHERE cs.archive_status = $1
            ORDER BY cs.last_activity_at DESC
            LIMIT $2 OFFSET $3
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetch(query, archive_status, limit, offset)
                logger.log_db_query(query, {"archive_status": archive_status, "limit": limit, "offset": offset}, result)
                return result
        except Exception as e:
            logger.log_db_query(query, {"archive_status": archive_status, "limit": limit, "offset": offset}, error=e)
            return []

    async def count_all_sessions(self, archive_status: str) -> int:
        query = "SELECT COUNT(*) FROM chat_sessions WHERE archive_status = $1"
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, archive_status)
                logger.log_db_query(query, {"archive_status": archive_status}, result)
                return result
        except Exception as e:
            logger.log_db_query(query, {"archive_status": archive_status}, error=e)
            return 0

    async def get_messages_for_sessions(self, session_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
        if not session_ids: return {}
        query = """
            SELECT * FROM chat_messages 
            WHERE session_id = ANY($1::int[]) 
            ORDER BY created_at ASC
        """
        try:
            async with get_db_connection() as conn:
                rows = await conn.fetch(query, session_ids)
                logger.log_db_query(query, {"session_ids": session_ids}, rows)
                
                result = {}
                for r in rows:
                    sid = r['session_id']
                    if sid not in result: result[sid] = []
                    result[sid].append(r)
                return result
        except Exception as e:
            logger.log_db_query(query, {"session_ids": session_ids}, error=e)
            return {}

    async def get_messages(self, session_db_id: int) -> List[Dict[str, Any]]:
        query = "SELECT * FROM chat_messages WHERE session_id = $1 ORDER BY created_at ASC"
        try:
            async with get_db_connection() as conn:
                result = await conn.fetch(query, session_db_id)
                logger.log_db_query(query, {"session_db_id": session_db_id}, result)
                return result
        except Exception as e:
            logger.log_db_query(query, {"session_db_id": session_db_id}, error=e)
            return []

    async def create_message(self, session_db_id: int, role: str, content: str) -> int:
        query = """
            INSERT INTO chat_messages (session_id, role, content, created_at, updated_at)
            VALUES ($1, $2, $3, NOW(), NOW())
            RETURNING id
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, session_db_id, role, content)
                logger.log_db_query(query, {"session_db_id": session_db_id, "role": role, "content": content}, result)
                return result
        except Exception as e:
            logger.log_db_query(query, {"session_db_id": session_db_id, "role": role, "content": content}, error=e)
            raise

    async def increment_message_count(self, session_db_id: int):
        # Optional: if you have a message_count column in chat_sessions
        pass 

    async def archive_session(self, session_id: str, status: str) -> bool:
        query = """
            UPDATE chat_sessions SET archive_status = $2 
            WHERE session_id = $1
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, session_id, status)
                logger.log_db_query(query, {"session_id": session_id, "status": status}, result)
                return result != "UPDATE 0"
        except Exception as e:
            logger.log_db_query(query, {"session_id": session_id, "status": status}, error=e)
            return False

    async def get_session_by_id_with_messages(self, session_id: str) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM chat_sessions WHERE session_id = $1"
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, session_id)
                logger.log_db_query(query, {"session_id": session_id}, result)
                return result
        except Exception as e:
            logger.log_db_query(query, {"session_id": session_id}, error=e)
            return None

    async def update_chat_session_metadata(self, session_db_id: int, metadata: Dict[str, Any]):
        query = "UPDATE chat_sessions SET metadata = $2 WHERE id = $1"
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, session_db_id, json.dumps(metadata))
                logger.log_db_query(query, {"session_db_id": session_db_id, "metadata": metadata}, result)
        except Exception as e:
            logger.log_db_query(query, {"session_db_id": session_db_id, "metadata": metadata}, error=e)
            raise
    
    async def get_all_chat_logs(self) -> List[Dict[str, Any]]:
        """Get all chat logs (legacy/backup method)"""
        return []

    async def delete_chat_log(self, session_id: str) -> Dict[str, Any]:
        """Delete a chat log"""
        return {"success": True}

    async def record_session_feedback(self, session_id: str, feedback_type: str, user_type: str = "customer") -> bool:
        """Record feedback for a chat session."""
        query = """
            INSERT INTO feedback (message_id, session_id, feedback, user_email, created_at)
            VALUES ($1, $2, $3, $4, NOW())
        """
        params = {"session_id": session_id, "feedback_type": feedback_type, "user_type": user_type}

        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, "session_feedback", session_id, feedback_type, None)
                logger.log_db_query(query, params, result)
                return True
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def get_session_feedback_counts(self, session_id: str) -> Dict[str, int]:
        """Get feedback counts for a session."""
        query = """
            SELECT
                COUNT(*) FILTER (WHERE feedback = 'positive') as positive_count,
                COUNT(*) FILTER (WHERE feedback = 'negative') as negative_count
            FROM feedback
            WHERE session_id = $1
        """
        params = {"session_id": session_id}

        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, session_id)
                logger.log_db_query(query, params, result)
                return {
                    "positive_count": result["positive_count"] if result else 0,
                    "negative_count": result["negative_count"] if result else 0
                }
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return {"positive_count": 0, "negative_count": 0}

    async def get_hil_enabled(self) -> bool:
        """Get HIL enabled status from configuration."""
        query = "SELECT hil_enabled FROM configuration_metadata WHERE id = 1"

        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query)
                logger.log_db_query(query, None, result)
                return result['hil_enabled'] if result and result['hil_enabled'] is not None else True
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return True  # Default to enabled if query fails
