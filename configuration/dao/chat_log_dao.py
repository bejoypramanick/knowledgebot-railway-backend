"""
Chat Log Data Access Object for Configuration Service
Handles database operations for chat logging
"""
from typing import Dict, List, Any, Optional
import json
from datetime import datetime

from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("chat_log_dao", "configuration")

class ChatLogDAO:
    def __init__(self):
        self.conn = None

    async def get_all_human_agents(self) -> List[str]:
        """Get all human agent emails."""
        query = """
            SELECT DISTINCT u.email
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE r.role_name = 'human_agent'
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                rows = await conn.fetch(query)
                logger.log_db_query(query, None, rows)
                return [r['email'] for r in rows]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def get_all_admins(self) -> List[str]:
        """Get all admin emails."""
        query = """
            SELECT DISTINCT u.email
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE r.role_name = 'admin'
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                rows = await conn.fetch(query)
                logger.log_db_query(query, None, rows)
                return [r['email'] for r in rows]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def check_user_role(self, email: str) -> Dict[str, bool]:
        """Check if user is agent or admin."""
        query = """
            SELECT 
                EXISTS(SELECT 1 FROM user_role_mapping urm 
                      JOIN users u ON urm.user_id = u.id 
                      JOIN roles r ON urm.role_id = r.id 
                      WHERE u.email = $1 AND r.role_name = 'human_agent') as is_agent,
                EXISTS(SELECT 1 FROM user_role_mapping urm 
                      JOIN users u ON urm.user_id = u.id 
                      JOIN roles r ON urm.role_id = r.id 
                      WHERE u.email = $1 AND r.role_name = 'admin') as is_admin
        """
        try:
            params = {"email": email}
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, email)
                logger.log_db_query(query, params, result)
                return {"is_agent": bool(result['is_agent']), "is_admin": bool(result['is_admin'])}
        except Exception as e:
            logger.log_db_query(query, {"email": email}, error=e)
            return {"is_agent": False, "is_admin": False}

    async def get_user_role_id(self, email: str) -> Optional[int]:
        """Get user_role_id for a given email."""
        query = """
            SELECT urm.user_role_id
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            WHERE u.email = $1
        """
        try:
            params = {"email": email}
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, email)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, {"email": email}, error=e)
            return None

    async def get_agent_chat_count(self, email: str) -> int:
        """Get active chat count for agent."""
        user_role_id = await self.get_user_role_id(email)
        if not user_role_id:
            return 0
            
        query = """
            SELECT COUNT(*) FROM session_assignments 
            WHERE user_role_id = $1 AND status = 'active'
        """
        try:
            params = {"user_role_id": user_role_id}
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, user_role_id)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, {"user_role_id": user_role_id}, error=e)
            return 0

    async def get_session_db_id(self, session_id: str) -> Optional[int]:
        """Get database ID for a session UUID string."""
        query = "SELECT id FROM chat_sessions WHERE session_id = $1"
        try:
            params = {"session_id": session_id}
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, session_id)
                logger.log_db_query(query, params, result)
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
            params = {"session_id": session_id, "metadata": metadata}
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, session_id, json.dumps(metadata))
                logger.log_db_query(query, params, result)
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
            params = {"session_db_id": session_db_id}
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, session_db_id)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, {"session_db_id": session_db_id}, error=e)
            return None

    async def update_session_assignment(self, session_db_id: int, email: str, type: str, status: str):
        """Update session assignment."""
        user_role_id = await self.get_user_role_id(email)
        if not user_role_id:
            raise ValueError(f"User role not found for email: {email}")
            
        query = """
            UPDATE session_assignments 
            SET user_role_id = $2, status = $3, assigned_at = NOW(), updated_at = NOW()
            WHERE session_id = $1
        """
        try:
            params = {"session_db_id": session_db_id, "user_role_id": user_role_id, "status": status}
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, session_db_id, user_role_id, status)
                logger.log_db_query(query, params, result)
        except Exception as e:
            logger.log_db_query(query, {"session_db_id": session_db_id, "user_role_id": user_role_id, "status": status}, error=e)
            raise

    async def create_session_assignment(self, session_db_id: int, email: str, type: str, status: str):
        """Create session assignment."""
        user_role_id = await self.get_user_role_id(email)
        if not user_role_id:
            raise ValueError(f"User role not found for email: {email}")
            
        query = """
            INSERT INTO session_assignments (session_id, user_role_id, status, assigned_at, created_at, updated_at)
            VALUES ($1, $2, $3, NOW(), NOW(), NOW())
        """
        try:
            params = {"session_db_id": session_db_id, "user_role_id": user_role_id, "status": status}
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, session_db_id, user_role_id, status)
                logger.log_db_query(query, params, result)
        except Exception as e:
            logger.log_db_query(query, {"session_db_id": session_db_id, "user_role_id": user_role_id, "status": status}, error=e)
            raise

    async def get_sessions_for_agent(self, email: str, archive_status: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        user_role_id = await self.get_user_role_id(email)
        if not user_role_id:
            return []

        # Handle 'all' status - return all sessions regardless of archive status
        if archive_status.lower() == 'all':
            query = """
                SELECT cs.*, u.email as agent_email
                FROM chat_sessions cs
                LEFT JOIN session_assignments sa ON cs.id = sa.session_id
                LEFT JOIN user_role_mapping urm ON sa.user_role_id = urm.user_role_id
                LEFT JOIN users u ON urm.user_id = u.id
                WHERE sa.user_role_id = $1
                ORDER BY cs.last_activity_at DESC
                LIMIT $2 OFFSET $3
            """
            try:
                params = {"user_role_id": user_role_id, "limit": limit, "offset": offset}
                logger.log_db_operation(query, params)
                async with get_db_connection() as conn:
                    result = await conn.fetch(query, user_role_id, limit, offset)
                    logger.log_db_query(query, params, result)
                    return result
            except Exception as e:
                logger.log_db_query(query, params, error=e)
                return []
        else:
            query = """
                SELECT cs.*, u.email as agent_email
                FROM chat_sessions cs
                LEFT JOIN session_assignments sa ON cs.id = sa.session_id
                LEFT JOIN user_role_mapping urm ON sa.user_role_id = urm.user_role_id
                LEFT JOIN users u ON urm.user_id = u.id
                WHERE sa.user_role_id = $1 AND cs.archive_status = $2
                ORDER BY cs.last_activity_at DESC
                LIMIT $3 OFFSET $4
            """
            try:
                params = {"user_role_id": user_role_id, "archive_status": archive_status, "limit": limit, "offset": offset}
                logger.log_db_operation(query, params)
                async with get_db_connection() as conn:
                    result = await conn.fetch(query, user_role_id, archive_status, limit, offset)
                    logger.log_db_query(query, params, result)
                    return result
            except Exception as e:
                logger.log_db_query(query, params, error=e)
                return []

    async def count_sessions_for_agent(self, email: str, archive_status: str) -> int:
        user_role_id = await self.get_user_role_id(email)
        if not user_role_id:
            return 0

        try:
            # Handle 'all' status - count all sessions regardless of archive status
            if archive_status.lower() == 'all':
                query = """
                    SELECT COUNT(*)
                    FROM chat_sessions cs
                    LEFT JOIN session_assignments sa ON cs.id = sa.session_id
                    WHERE sa.user_role_id = $1
                """
                params = {"user_role_id": user_role_id}
                logger.log_db_operation(query, params)
                async with get_db_connection() as conn:
                    result = await conn.fetchval(query, user_role_id)
                    logger.log_db_query(query, params, result)
                    return result
            else:
                query = """
                    SELECT COUNT(*)
                    FROM chat_sessions cs
                    LEFT JOIN session_assignments sa ON cs.id = sa.session_id
                    WHERE sa.user_role_id = $1 AND cs.archive_status = $2
                """
                params = {"user_role_id": user_role_id, "archive_status": archive_status}
                logger.log_db_operation(query, params)
                async with get_db_connection() as conn:
                    result = await conn.fetchval(query, user_role_id, archive_status)
                    logger.log_db_query(query, params, result)
                    return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return 0

    async def get_all_sessions(self, archive_status: str, limit: int, offset: int) -> List[Dict[str, Any]]:
        # Handle 'all' status - return all sessions regardless of archive status
        if archive_status.lower() == 'all':
            query = """
                SELECT cs.*, u.email as agent_email
                FROM chat_sessions cs
                LEFT JOIN session_assignments sa ON cs.id = sa.session_id AND sa.status = 'active'
                LEFT JOIN user_role_mapping urm ON sa.user_role_id = urm.user_role_id
                LEFT JOIN users u ON urm.user_id = u.id
                ORDER BY cs.last_activity_at DESC
                LIMIT $1 OFFSET $2
            """
            try:
                params = {"limit": limit, "offset": offset}
                logger.log_db_operation(query, params)
                async with get_db_connection() as conn:
                    result = await conn.fetch(query, limit, offset)
                    logger.log_db_query(query, params, result)
                    return result
            except Exception as e:
                logger.log_db_query(query, params, error=e)
                return []
        else:
            query = """
                SELECT cs.*, u.email as agent_email
                FROM chat_sessions cs
                LEFT JOIN session_assignments sa ON cs.id = sa.session_id AND sa.status = 'active'
                LEFT JOIN user_role_mapping urm ON sa.user_role_id = urm.user_role_id
                LEFT JOIN users u ON urm.user_id = u.id
                WHERE cs.archive_status = $1
                ORDER BY cs.last_activity_at DESC
                LIMIT $2 OFFSET $3
            """
            try:
                params = {"archive_status": archive_status, "limit": limit, "offset": offset}
                logger.log_db_operation(query, params)
                async with get_db_connection() as conn:
                    result = await conn.fetch(query, archive_status, limit, offset)
                    logger.log_db_query(query, params, result)
                    return result
            except Exception as e:
                logger.log_db_query(query, params, error=e)
                return []

    async def count_all_sessions(self, archive_status: str) -> int:
        try:
            # Handle 'all' status - count all sessions regardless of archive status
            if archive_status.lower() == 'all':
                query = "SELECT COUNT(*) FROM chat_sessions"
                params = {}
                logger.log_db_operation(query, params)
                async with get_db_connection() as conn:
                    result = await conn.fetchval(query)
                    logger.log_db_query(query, params, result)
                    return result
            else:
                query = "SELECT COUNT(*) FROM chat_sessions WHERE archive_status = $1"
                params = {"archive_status": archive_status}
                logger.log_db_operation(query, params)
                async with get_db_connection() as conn:
                    result = await conn.fetchval(query, archive_status)
                    logger.log_db_query(query, params, result)
                    return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return 0

    async def get_messages_for_sessions(self, session_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
        if not session_ids: return {}
        # Generate dynamic placeholders for IN clause
        placeholders = ','.join(f'${i+1}' for i in range(len(session_ids)))
        query = f"""
            SELECT * FROM chat_messages
            WHERE session_id IN ({placeholders})
            ORDER BY created_at ASC
        """
        try:
            params = {"session_ids": session_ids}
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                rows = await conn.fetch(query, *session_ids)
                logger.log_db_query(query, params, rows)
                
                result = {}
                for r in rows:
                    sid = r['session_id']
                    if sid not in result: result[sid] = []
                    result[sid].append(r)
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return {}

    async def get_messages(self, session_db_id: int) -> List[Dict[str, Any]]:
        query = "SELECT * FROM chat_messages WHERE session_id = $1 ORDER BY created_at ASC"
        try:
            params = {"session_db_id": session_db_id}
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetch(query, session_db_id)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return []

    async def create_message(self, session_db_id: int, role: str, content: str) -> int:
        query = """
            INSERT INTO chat_messages (session_id, role, content, created_at, updated_at)
            VALUES ($1, $2, $3, NOW(), NOW())
            RETURNING id
        """
        try:
            params = {"session_db_id": session_db_id, "role": role, "content": content}
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, session_db_id, role, content)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
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
            params = {"session_id": session_id, "status": status}
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, session_id, status)
                logger.log_db_query(query, params, result)
                return result != "UPDATE 0"
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False

    async def get_session_by_id_with_messages(self, session_id: str) -> Optional[Dict[str, Any]]:
        query = "SELECT * FROM chat_sessions WHERE session_id = $1"
        try:
            params = {"session_id": session_id}
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, session_id)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def update_chat_session_metadata(self, session_db_id: int, metadata: Dict[str, Any]):
        query = "UPDATE chat_sessions SET metadata = $2 WHERE id = $1"
        try:
            params = {"session_db_id": session_db_id, "metadata": metadata}
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, session_db_id, json.dumps(metadata))
                logger.log_db_query(query, params, result)
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise
    
    async def get_all_chat_logs(self) -> List[Dict[str, Any]]:
        """Get all chat logs (legacy/backup method)"""
        return []

    async def delete_chat_log(self, session_id: str) -> Dict[str, Any]:
        """Delete a chat log"""
        return {"success": True}

    async def record_session_feedback(self, session_id: str, feedback_type: str, user_role_id: Optional[int] = None) -> bool:
        """Record feedback for a chat session."""
        query = """
            INSERT INTO chat_feedback (message_id, session_id, feedback_type, user_role_id, created_at)
            VALUES ($1, $2, $3, $4, NOW())
        """
        params = {"session_id": session_id, "feedback_type": feedback_type, "user_role_id": user_role_id}

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, "session_feedback", session_id, feedback_type, user_role_id)
                logger.log_db_query(query, params, result)
                return True
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def get_session_feedback_counts(self, session_id: str) -> Dict[str, int]:
        """Get feedback counts for a session."""
        query = """
            SELECT
                COUNT(*) FILTER (WHERE feedback_type = 'positive') as positive_count,
                COUNT(*) FILTER (WHERE feedback_type = 'negative') as negative_count
            FROM chat_feedback
            WHERE session_id = $1
        """
        params = {"session_id": session_id}

        try:
            logger.log_db_operation(query, params)
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

    async def get_batch_feedback_counts(self, session_ids: List[str]) -> Dict[str, Dict[str, int]]:
        """Get feedback counts for multiple sessions in a single query (fixes N+1 problem)."""
        if not session_ids:
            return {}

        # Generate dynamic placeholders for IN clause
        placeholders = ','.join(f'${i+1}' for i in range(len(session_ids)))
        query = f"""
            SELECT
                session_id,
                COUNT(*) FILTER (WHERE feedback_type = 'positive') as positive_count,
                COUNT(*) FILTER (WHERE feedback_type = 'negative') as negative_count
            FROM chat_feedback
            WHERE session_id IN ({placeholders})
            GROUP BY session_id
        """
        params = {"session_ids": session_ids}

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                rows = await conn.fetch(query, *session_ids)
                logger.log_db_query(query, params, rows)
                
                # Build result dictionary
                result = {}
                for row in rows:
                    result[row["session_id"]] = {
                        "positive_count": row["positive_count"] or 0,
                        "negative_count": row["negative_count"] or 0
                    }
                
                # Fill in missing sessions with zero counts
                for session_id in session_ids:
                    if session_id not in result:
                        result[session_id] = {"positive_count": 0, "negative_count": 0}
                
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            # Return empty counts for all sessions on error
            return {sid: {"positive_count": 0, "negative_count": 0} for sid in session_ids}

    async def get_hil_enabled(self) -> bool:
        """Get HIL enabled status from configuration."""
        query = "SELECT hil_enabled FROM widget_configuration WHERE id = 1"

        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query)
                logger.log_db_query(query, None, result)
                return result['hil_enabled'] if result and result['hil_enabled'] is not None else True
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return True  # Default to enabled if query fails

    async def delete_messages_for_session(self, session_db_id: int) -> bool:
        """Delete all messages for a chat session."""
        query = "DELETE FROM chat_messages WHERE session_id = $1"
        try:
            params = {"session_db_id": session_db_id}
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, session_db_id)
                logger.log_db_query(query, params, result)
                return True
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def delete_chat_session_by_id(self, session_db_id: int) -> bool:
        """Delete a chat session by its database ID."""
        query = "DELETE FROM chat_sessions WHERE id = $1"
        try:
            params = {"session_db_id": session_db_id}
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, session_db_id)
                logger.log_db_query(query, params, result)
                return True
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def update_messages_status_for_session(self, session_db_id: int, status: str) -> bool:
        """Update message status for all messages in a session."""
        query = "UPDATE chat_messages SET status = $2, updated_at = NOW() WHERE session_id = $1"
        try:
            params = {"session_db_id": session_db_id, "status": status}
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, session_db_id, status)
                logger.log_db_query(query, params, result)
                return True
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise
