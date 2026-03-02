"""
Chat Log Data Access Object for Configuration Service
Handles database operations for chat logging
"""
from typing import Dict, List, Any, Optional
import json
from datetime import datetime

from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
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
            async with get_db_session() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
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
            async with get_db_session() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
                logger.log_db_query(query, None, rows)
                return [r['email'] for r in rows]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def check_user_role(self, email: str) -> Dict[str, bool]:
        """Check if user is agent or admin."""
        # Use CAST to ensure proper boolean type from PostgreSQL
        # This forces SQLAlchemy to handle the type conversion correctly
        query = """
            SELECT
                CAST(EXISTS(SELECT 1 FROM user_role_mapping urm
                      JOIN users u ON urm.user_id = u.id
                      JOIN roles r ON urm.role_id = r.id
                      WHERE u.email = :email AND r.role_name = 'human_agent') AS BOOLEAN) as is_agent,
                CAST(EXISTS(SELECT 1 FROM user_role_mapping urm
                      JOIN users u ON urm.user_id = u.id
                      JOIN roles r ON urm.role_id = r.id
                      WHERE u.email = :email AND r.role_name = 'admin') AS BOOLEAN) as is_admin
        """
        try:
            params = {"email": email}
            logger.info(f"🔍 DEBUG check_user_role: Checking email: {email}")
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                logger.info(f"🔍 DEBUG check_user_role: Query result row: {row}")
                logger.log_db_query(query, params, row)
                if row:
                    # Convert tuple/Row to dict for consistent access
                    row_dict = dict(row._mapping) if hasattr(row, '_mapping') else {'is_agent': row[0], 'is_admin': row[1]}
                    logger.info(f"🔍 DEBUG check_user_role: Converted row_dict: {row_dict}")

                    # Helper to handle any boolean representation from database
                    def convert_bool(value):
                        if isinstance(value, bool):
                            return value
                        if isinstance(value, str):
                            return value.lower() in ('true', 't', '1', 'yes')
                        return bool(value)

                    is_agent = convert_bool(row_dict.get('is_agent', False))
                    is_admin = convert_bool(row_dict.get('is_admin', False))
                    logger.info(f"🔍 DEBUG check_user_role: Final result - is_agent={is_agent}, is_admin={is_admin}")
                    return {"is_agent": is_agent, "is_admin": is_admin}
                logger.info(f"🔍 DEBUG check_user_role: No row returned, returning false roles")
                return {"is_agent": False, "is_admin": False}
        except Exception as e:
            logger.error(f"🔍 DEBUG check_user_role: Exception occurred: {type(e).__name__}: {e}")
            logger.log_db_query(query, {"email": email}, error=e)
            return {"is_agent": False, "is_admin": False}

    async def get_user_role_id(self, email: str) -> Optional[int]:
        """Get user_role_id for a given email."""
        query = """
            SELECT urm.user_role_id
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            WHERE u.email = :email
        """
        try:
            params = {"email": email}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                logger.log_db_query(query, params, row)
                return row[0] if row else None
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
            WHERE user_role_id = :user_role_id AND status = 'active'
        """
        try:
            params = {"user_role_id": user_role_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                count = result.scalar()
                logger.log_db_query(query, params, count)
                return count or 0
        except Exception as e:
            logger.log_db_query(query, {"user_role_id": user_role_id}, error=e)
            return 0

    async def get_session_db_id(self, session_id: int | str) -> Optional[int]:
        """Get database ID for a session (numeric ID only)."""
        try:
            # Convert to int if string
            session_db_id = int(session_id) if isinstance(session_id, str) else session_id

            query = "SELECT id FROM chat_sessions WHERE id = :id"
            params = {"id": session_db_id}

            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                logger.log_db_query(query, params, row)
                return row[0] if row else None
        except Exception as e:
            logger.log_db_query("get_session_db_id", {"session_id": session_id}, error=e)
            return None

    async def get_session_db_id_by_uuid(self, session_uuid: str) -> Optional[int]:
        """Get database ID for a session by its session_id (UUID) column.
        Used for special cases like heartbeat sessions that use string UUIDs."""
        try:
            query = "SELECT id FROM chat_sessions WHERE session_id = :session_id"
            params = {"session_id": session_uuid}

            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                logger.log_db_query(query, params, row)
                return row[0] if row else None
        except Exception as e:
            logger.log_db_query("get_session_db_id_by_uuid", {"session_uuid": session_uuid}, error=e)
            return None

    async def create_chat_session(self, session_id: str, metadata: Dict[str, Any]) -> int:
        """Create a new chat session."""
        query = """
            INSERT INTO chat_sessions (session_id, metadata, created_at, last_activity_at, is_active)
            VALUES (:session_id, :metadata, NOW(), NOW(), true)
            RETURNING id
        """
        try:
            params = {"session_id": session_id, "metadata": json.dumps(metadata)}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                await session.commit()
                logger.log_db_query(query, params, row)
                return row[0] if row else None
        except Exception as e:
            logger.log_db_query(query, {"session_id": session_id, "metadata": metadata}, error=e)
            raise

    async def get_assignee_type(self, email: str) -> str:
        """Determine if email belongs to agent or admin."""
        roles = await self.check_user_role(email)
        if roles['is_agent']: return 'agent'
        if roles['is_admin']: return 'admin'
        return 'system'

    async def get_session_assignment(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get assignment for a session."""
        query = "SELECT * FROM session_assignments WHERE session_id = :session_id"
        try:
            params = {"session_id": session_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                logger.log_db_query(query, params, row)
                return dict(row._mapping) if row else None
        except Exception as e:
            logger.log_db_query(query, {"session_id": session_id}, error=e)
            return None

    async def update_session_assignment(self, session_id: str, email: str, type: str, status: str):
        """Update session assignment."""
        user_role_id = await self.get_user_role_id(email)
        if not user_role_id:
            raise ValueError(f"User role not found for email: {email}")

        query = """
            UPDATE session_assignments
            SET user_role_id = :user_role_id, status = :status, assigned_at = NOW(), updated_at = NOW()
            WHERE session_id = :session_id
        """
        try:
            params = {"session_id": session_id, "user_role_id": user_role_id, "status": status}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
        except Exception as e:
            logger.log_db_query(query, {"session_id": session_id, "user_role_id": user_role_id, "status": status}, error=e)
            raise

    async def create_session_assignment(self, session_db_id: int, email: str, type: str, status: str):
        """Create session assignment."""
        user_role_id = await self.get_user_role_id(email)
        if not user_role_id:
            raise ValueError(f"User role not found for email: {email}")

        query = """
            INSERT INTO session_assignments (session_id, user_role_id, status, assigned_at, created_at, updated_at)
            VALUES (:session_id, :user_role_id, :status, NOW(), NOW(), NOW())
        """
        try:
            params = {"session_id": session_db_id, "user_role_id": user_role_id, "status": status}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
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
                WHERE sa.user_role_id = :user_role_id
                ORDER BY cs.last_activity_at DESC
                LIMIT :limit OFFSET :offset
            """
            try:
                params = {"user_role_id": user_role_id, "limit": limit, "offset": offset}
                logger.log_db_operation(query, params)
                async with get_db_session() as session:
                    result = await session.execute(text(query), params)
                    rows = result.fetchall()
                    logger.log_db_query(query, params, rows)
                    return [dict(row._mapping) for row in rows]
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
                WHERE sa.user_role_id = :user_role_id AND cs.archive_status = :archive_status
                ORDER BY cs.last_activity_at DESC
                LIMIT :limit OFFSET :offset
            """
            try:
                params = {"user_role_id": user_role_id, "archive_status": archive_status, "limit": limit, "offset": offset}
                logger.log_db_operation(query, params)
                async with get_db_session() as session:
                    result = await session.execute(text(query), params)
                    rows = result.fetchall()
                    logger.log_db_query(query, params, rows)
                    return [dict(row._mapping) for row in rows]
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
                    WHERE sa.user_role_id = :user_role_id
                """
                params = {"user_role_id": user_role_id}
                logger.log_db_operation(query, params)
                async with get_db_session() as session:
                    result = await session.execute(text(query), params)
                    count = result.scalar()
                    logger.log_db_query(query, params, count)
                    return count or 0
            else:
                query = """
                    SELECT COUNT(*)
                    FROM chat_sessions cs
                    LEFT JOIN session_assignments sa ON cs.id = sa.session_id
                    WHERE sa.user_role_id = :user_role_id AND cs.archive_status = :archive_status
                """
                params = {"user_role_id": user_role_id, "archive_status": archive_status}
                logger.log_db_operation(query, params)
                async with get_db_session() as session:
                    result = await session.execute(text(query), params)
                    count = result.scalar()
                    logger.log_db_query(query, params, count)
                    return count or 0
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
                LIMIT :limit OFFSET :offset
            """
            try:
                params = {"limit": limit, "offset": offset}
                logger.log_db_operation(query, params)
                async with get_db_session() as session:
                    result = await session.execute(text(query), params)
                    rows = result.fetchall()
                    logger.log_db_query(query, params, rows)
                    return [dict(row._mapping) for row in rows]
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
                WHERE cs.archive_status = :archive_status
                ORDER BY cs.last_activity_at DESC
                LIMIT :limit OFFSET :offset
            """
            try:
                params = {"archive_status": archive_status, "limit": limit, "offset": offset}
                logger.log_db_operation(query, params)
                async with get_db_session() as session:
                    result = await session.execute(text(query), params)
                    rows = result.fetchall()
                    logger.log_db_query(query, params, rows)
                    return [dict(row._mapping) for row in rows]
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
                async with get_db_session() as session:
                    result = await session.execute(text(query), params)
                    count = result.scalar()
                    logger.log_db_query(query, params, count)
                    return count or 0
            else:
                query = "SELECT COUNT(*) FROM chat_sessions WHERE archive_status = :archive_status"
                params = {"archive_status": archive_status}
                logger.log_db_operation(query, params)
                async with get_db_session() as session:
                    result = await session.execute(text(query), params)
                    count = result.scalar()
                    logger.log_db_query(query, params, count)
                    return count or 0
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return 0

    async def get_messages_for_sessions(self, session_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
        """Get messages for multiple sessions by their numeric IDs."""
        if not session_ids: return {}

        # Ensure all IDs are integers (may come as strings from database)
        int_session_ids = [int(sid) if isinstance(sid, str) else sid for sid in session_ids]

        # Build SQL with proper array syntax for asyncpg
        # Use CAST to ensure proper type handling with parameter binding
        query = """
            SELECT * FROM chat_messages
            WHERE session_id = ANY(ARRAY[:session_ids])
            ORDER BY created_at ASC;
        """
        params = {"session_ids": int_session_ids}

        try:
            logger.log_db_operation(query, params)
            logger.info(f"🔍 get_messages_for_sessions: Querying for {len(int_session_ids)} sessions: {int_session_ids[:5]}...")
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                rows = result.fetchall()
                logger.info(f"🔍 get_messages_for_sessions: query returned {len(rows)} rows for {len(int_session_ids)} session_ids: {int_session_ids[:5]}")
                logger.log_db_query(query, params, rows)

                result_dict = {}
                for r in rows:
                    sid = r['id']
                    # Ensure sid is converted to int (may be stored as text in database)
                    sid_int = int(sid) if isinstance(sid, str) else sid
                    if sid_int not in result_dict: result_dict[sid_int] = []
                    result_dict[sid_int].append(dict(r._mapping))
                logger.info(f"📊 get_messages_for_sessions result: {len(result_dict)} sessions with messages, raw sids: {list(result_dict.keys())[:5]}")
                return result_dict
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            logger.error(f"Error fetching messages for sessions: {e}")
            return {}

    async def get_messages(self, session_db_id: int) -> List[Dict[str, Any]]:
        query = "SELECT * FROM chat_messages WHERE session_id = :session_db_id ORDER BY created_at ASC"
        try:
            params = {"session_db_id": session_db_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                rows = result.fetchall()
                logger.log_db_query(query, params, rows)
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return []

    async def create_message(self, session_db_id: int, role: str, content: str) -> int:
        query = """
            INSERT INTO chat_messages (session_id, role, content, created_at, updated_at)
            VALUES (:session_db_id, :role, :content, NOW(), NOW())
            RETURNING id
        """
        try:
            params = {"session_db_id": session_db_id, "role": role, "content": content}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                await session.commit()
                logger.log_db_query(query, params, row)
                return row[0] if row else None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def increment_message_count(self, session_db_id: int):
        # Optional: if you have a message_count column in chat_sessions
        pass 

    async def archive_session(self, session_id: int | str, status: str) -> bool:
        """Archive a session using numeric ID only."""
        try:
            # Convert to int if string
            session_db_id = int(session_id) if isinstance(session_id, str) else session_id

            query = """
                UPDATE chat_sessions SET archive_status = :status
                WHERE id = :id
            """
            params = {"id": session_db_id, "status": status}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
                return result.rowcount > 0 if hasattr(result, 'rowcount') else True
        except Exception as e:
            logger.log_db_query(query, {"session_id": session_id, "status": status}, error=e)
            return False

    async def get_session_by_id_with_messages(self, session_id: int | str) -> Optional[Dict[str, Any]]:
        """Get session by numeric ID only."""
        try:
            # Convert to int if string
            session_db_id = int(session_id) if isinstance(session_id, str) else session_id

            query = "SELECT * FROM chat_sessions WHERE id = :id"
            params = {"id": session_db_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                logger.log_db_query(query, params, row)
                return dict(row._mapping) if row else None
        except Exception as e:
            logger.log_db_query(query, {"session_id": session_id}, error=e)
            return None

    async def update_chat_session_metadata(self, session_db_id: int, metadata: Dict[str, Any]):
        query = "UPDATE chat_sessions SET metadata = :metadata WHERE id = :session_db_id"
        try:
            params = {"session_db_id": session_db_id, "metadata": json.dumps(metadata)}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise
    
    async def get_all_chat_logs(self) -> List[Dict[str, Any]]:
        """Get all chat logs (legacy/backup method)"""
        return []

    async def delete_chat_log(self, session_id: str) -> Dict[str, Any]:
        """Delete a chat log"""
        return {"success": True}

    async def get_session_feedback_counts(self, session_id: str) -> Dict[str, int]:
        """Get feedback counts for a session."""
        query = """
            SELECT
                COUNT(*) FILTER (WHERE feedback_type = 'positive') as positive_count,
                COUNT(*) FILTER (WHERE feedback_type = 'negative') as negative_count
            FROM chat_feedback
            WHERE session_id = :session_id
        """
        params = {"session_id": session_id}

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                logger.log_db_query(query, params, row)
                return {
                    "positive_count": row["positive_count"] if row else 0,
                    "negative_count": row["negative_count"] if row else 0
                }
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return {"positive_count": 0, "negative_count": 0}

    async def get_batch_feedback_counts(self, session_ids: List[str]) -> Dict[str, Dict[str, int]]:
        """Get feedback counts for multiple sessions in a single query (fixes N+1 problem)."""
        if not session_ids:
            return {}

        # Build dynamic IN clause for asyncpg compatibility
        placeholders = ",".join([f":id_{i}" for i in range(len(session_ids))])
        params = {f"id_{i}": sid for i, sid in enumerate(session_ids)}

        query = f"""
            SELECT
                session_id,
                COUNT(*) FILTER (WHERE feedback_type = 'positive') as positive_count,
                COUNT(*) FILTER (WHERE feedback_type = 'negative') as negative_count
            FROM chat_feedback
            WHERE session_id IN ({placeholders})
            GROUP BY session_id
        """

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                rows = result.fetchall()
                logger.log_db_query(query, params, rows)

                # Build result dictionary
                result_dict = {}
                for row in rows:
                    result_dict[row["session_id"]] = {
                        "positive_count": row["positive_count"] or 0,
                        "negative_count": row["negative_count"] or 0
                    }

                # Fill in missing sessions with zero counts
                for session_id in session_ids:
                    if session_id not in result_dict:
                        result_dict[session_id] = {"positive_count": 0, "negative_count": 0}

                return result_dict
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            # Return empty counts for all sessions on error
            return {sid: {"positive_count": 0, "negative_count": 0} for sid in session_ids}

    async def get_hil_enabled(self) -> bool:
        """Get HIL enabled status from configuration."""
        # Use CAST to ensure proper boolean type from PostgreSQL
        query = "SELECT CAST(hil_enabled AS BOOLEAN) FROM widget_configuration WHERE id = 1"

        try:
            logger.log_db_operation(query)
            async with get_db_session() as session:
                result = await session.execute(text(query))
                row = result.fetchone()
                logger.log_db_query(query, None, row)
                if row:
                    # Convert tuple/Row to dict for consistent access
                    row_dict = dict(row._mapping) if hasattr(row, '_mapping') else {'hil_enabled': row[0]}

                    # Handle any boolean representation from database
                    hil_value = row_dict.get('hil_enabled', True)
                    if isinstance(hil_value, bool):
                        return hil_value
                    if isinstance(hil_value, str):
                        return hil_value.lower() in ('true', 't', '1', 'yes')
                    return bool(hil_value)
                return True  # Default to enabled if no row found
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return True  # Default to enabled if query fails

    async def delete_messages_for_session(self, session_db_id: int) -> bool:
        """Delete all messages for a chat session."""
        query = "DELETE FROM chat_messages WHERE session_id = :session_db_id"
        try:
            params = {"session_db_id": session_db_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
                return True
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def delete_chat_session_by_id(self, session_db_id: int) -> bool:
        """Delete a chat session by its database ID."""
        query = "DELETE FROM chat_sessions WHERE id = :session_db_id"
        try:
            params = {"session_db_id": session_db_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
                return True
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def update_messages_status_for_session(self, session_db_id: int, status: str) -> bool:
        """Update message status for all messages in a session."""
        query = "UPDATE chat_messages SET status = :status, updated_at = NOW() WHERE session_id = :session_db_id"
        try:
            params = {"session_db_id": session_db_id, "status": status}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
                return True
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def mark_message_as_read(self, message_id: int) -> bool:
        """Mark a single message as read by human agent or admin."""
        query = "UPDATE chat_messages SET is_message_read = true, updated_at = NOW() WHERE id = :message_id"
        try:
            params = {"message_id": message_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
                return True
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False

    async def mark_session_messages_as_read(self, session_id: int) -> bool:
        """Mark all messages in a session as read by human agent or admin."""
        query = "UPDATE chat_messages SET is_message_read = true, updated_at = NOW() WHERE session_id = :session_id"
        try:
            params = {"session_id": session_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
                return True
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False

    async def get_unread_messages_count(self, session_id: int) -> int:
        """Get count of unread messages in a session."""
        query = "SELECT COUNT(*) as count FROM chat_messages WHERE session_id = :session_id AND is_message_read = false"
        try:
            params = {"session_id": session_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                count = result.scalar()
                logger.log_db_query(query, params, count)
                return count or 0
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return 0
