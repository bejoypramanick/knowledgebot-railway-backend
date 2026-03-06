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
                return [dict(r._mapping)['email'] for r in rows] if rows else []  # Use mapping for dictionary access
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
                return [dict(r._mapping)['email'] for r in rows] if rows else []  # Use mapping for dictionary access
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
            INSERT INTO session_assignments (session_id, user_role_id, status, assigned_at, updated_at)
            VALUES (:session_id, :user_role_id, :status, NOW(), NOW())
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
        import time
        start_time = time.time()
        logger.info(f"🔍 [CHATLOG-DAO] get_all_sessions called: archive_status={archive_status}, limit={limit}, offset={offset}")
        
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
                logger.info(f"🔍 [CHATLOG-DAO] Executing query with params: {params}")
                logger.log_db_operation(query, params)
                
                db_start = time.time()
                async with get_db_session() as session:
                    result = await session.execute(text(query), params)
                    rows = result.fetchall()
                db_duration = time.time() - db_start
                
                logger.info(f"⏱️ [CHATLOG-DAO] Query returned {len(rows)} rows in {db_duration:.2f}s (total: {time.time() - start_time:.2f}s)")
                logger.log_db_query(query, params, rows)
                return [dict(row._mapping) for row in rows]
            except Exception as e:
                logger.error(f"❌ [CHATLOG-DAO] Error in get_all_sessions after {time.time() - start_time:.2f}s: {e}")
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
                logger.info(f"🔍 [CHATLOG-DAO] Executing query with params: {params}")
                logger.log_db_operation(query, params)
                
                db_start = time.time()
                async with get_db_session() as session:
                    result = await session.execute(text(query), params)
                    rows = result.fetchall()
                db_duration = time.time() - db_start
                
                logger.info(f"⏱️ [CHATLOG-DAO] Query returned {len(rows)} rows in {db_duration:.2f}s (total: {time.time() - start_time:.2f}s)")
                logger.log_db_query(query, params, rows)
                return [dict(row._mapping) for row in rows]
            except Exception as e:
                logger.error(f"❌ [CHATLOG-DAO] Error in get_all_sessions after {time.time() - start_time:.2f}s: {e}")
                logger.log_db_query(query, params, error=e)
                return []

    async def count_all_sessions(self, archive_status: str) -> int:
        import time
        start_time = time.time()
        
        try:
            # Handle 'all' status - count all sessions regardless of archive status
            if archive_status.lower() == 'all':
                query = "SELECT COUNT(*) FROM chat_sessions"
                params = {}
                logger.log_db_operation(query, params)
                
                db_start = time.time()
                async with get_db_session() as session:
                    result = await session.execute(text(query), params)
                    count = result.scalar()
                db_duration = time.time() - db_start
                
                logger.info(f"⏱️ [CHATLOG-DAO] count_all_sessions returned {count} in {db_duration:.2f}s")
                logger.log_db_query(query, params, count)
                return count or 0
            else:
                query = "SELECT COUNT(*) FROM chat_sessions WHERE archive_status = :archive_status"
                params = {"archive_status": archive_status}
                logger.log_db_operation(query, params)
                
                db_start = time.time()
                async with get_db_session() as session:
                    result = await session.execute(text(query), params)
                    count = result.scalar()
                db_duration = time.time() - db_start
                
                logger.info(f"⏱️ [CHATLOG-DAO] count_all_sessions (filtered) returned {count} in {db_duration:.2f}s")
                logger.log_db_query(query, params, count)
                return count or 0
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return 0

    async def get_messages_for_sessions(self, session_ids: List[int]) -> Dict[int, List[Dict[str, Any]]]:
        """Get messages for multiple sessions using single LEFT JOIN query."""
        if not session_ids: return {}

        # Ensure all IDs are integers
        int_session_ids = [int(sid) if isinstance(sid, str) else sid for sid in session_ids]

        # Single LEFT JOIN query: get all messages for selected sessions in one go
        query = """
            SELECT cm.*
            FROM chat_sessions cs
            LEFT JOIN chat_messages cm ON cs.id = cm.session_id
            WHERE cs.id = ANY(:session_ids)
            ORDER BY cs.id, cm.created_at ASC
        """
        params = {"session_ids": int_session_ids}

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                rows = result.fetchall()

                # Group messages by session_id, skip NULL message rows
                result_dict = {}
                for r in rows:
                    # Skip rows where message is NULL (session has no messages)
                    if r['id'] is None:
                        continue

                    session_id = r['session_id']
                    if session_id not in result_dict:
                        result_dict[session_id] = []
                    result_dict[session_id].append(dict(r._mapping))

                return result_dict
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            logger.error(f"Error fetching messages: {e}")
            return {}

    async def get_latest_message_for_session(self, session_id: int) -> Optional[Dict[str, Any]]:
        """Get the latest message for a single session."""
        query = """
            SELECT * FROM chat_messages
            WHERE session_id = :session_id
            ORDER BY created_at DESC
            LIMIT 1
        """
        try:
            params = {"session_id": session_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                return dict(row._mapping) if row else None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def get_latest_messages_batch(self, session_ids: List[int]) -> Dict[int, Dict[str, Any]]:
        """Get the latest message for multiple sessions in a single query (OPTIMIZED)."""
        import time
        start_time = time.time()
        
        if not session_ids:
            return {}

        logger.info(f"🔍 [CHATLOG-DAO] get_latest_messages_batch called for {len(session_ids)} sessions")
        
        # Use a simpler approach: for each session, get the message with MAX(id)
        query = """
            SELECT cm.*
            FROM chat_messages cm
            INNER JOIN (
                SELECT session_id, MAX(id) as max_id
                FROM chat_messages
                WHERE session_id = ANY(:session_ids)
                GROUP BY session_id
            ) latest ON cm.session_id = latest.session_id AND cm.id = latest.max_id
        """
        
        try:
            params = {"session_ids": session_ids}
            logger.log_db_operation(query, params)
            
            db_start = time.time()
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                rows = result.fetchall()
            db_duration = time.time() - db_start
            
            result_dict = {row.session_id: dict(row._mapping) for row in rows}
            logger.info(f"⏱️ [CHATLOG-DAO] Fetched {len(result_dict)} latest messages in {db_duration:.2f}s (total: {time.time() - start_time:.2f}s)")
            
            return result_dict
        except Exception as e:
            logger.error(f"❌ [CHATLOG-DAO] Error in get_latest_messages_batch after {time.time() - start_time:.2f}s: {e}")
            logger.log_db_query(query, params, error=e)
            return {}


    async def get_session_messages(self, session_id: int) -> List[Dict[str, Any]]:
        """Get all messages for a single session (full conversation)."""
        query = """
            SELECT * FROM chat_messages
            WHERE session_id = :session_id
            ORDER BY created_at ASC
        """
        try:
            params = {"session_id": session_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                rows = result.fetchall()
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

    async def update_session_feedback(self, session_id: int | str, feedback_type: str) -> bool:
        """
        Update session feedback (thumbs up/down).
        
        Args:
            session_id: Session ID (numeric or string)
            feedback_type: 'positive' or 'negative'
        
        Returns:
            True if updated successfully
        """
        try:
            # Convert to int if string
            session_db_id = int(session_id) if isinstance(session_id, str) else session_id

            query = """
                UPDATE chat_sessions 
                SET feedback_type = :feedback_type,
                    feedback_provided_at = NOW()
                WHERE id = :id
            """
            params = {"id": session_db_id, "feedback_type": feedback_type}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
                logger.info(f"✅ Feedback '{feedback_type}' saved for session {session_db_id}")
                return result.rowcount > 0 if hasattr(result, 'rowcount') else True
        except Exception as e:
            logger.error(f"❌ Error updating session feedback: {e}")
            logger.log_db_query(query, {"session_id": session_id, "feedback_type": feedback_type}, error=e)
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
        """Get feedback counts for a session (returns 1 or 0 for each type since each session has only one feedback)."""
        query = """
            SELECT
                feedback_type
            FROM chat_sessions
            WHERE session_id = :session_id
        """
        params = {"session_id": session_id}

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                logger.log_db_query(query, params, row)
                
                if row and row['feedback_type']:
                    feedback_type = row['feedback_type']
                    return {
                        "positive_count": 1 if feedback_type == 'positive' else 0,
                        "negative_count": 1 if feedback_type == 'negative' else 0
                    }
                return {"positive_count": 0, "negative_count": 0}
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return {"positive_count": 0, "negative_count": 0}

    async def get_batch_feedback_counts(self, session_ids: List[str]) -> Dict[str, Dict[str, int]]:
        """Get feedback for multiple sessions in a single query."""
        import time
        start_time = time.time()
        
        if not session_ids:
            return {}

        logger.info(f"🔍 [CHATLOG-DAO] get_batch_feedback_counts called for {len(session_ids)} sessions")

        # Build dynamic IN clause for asyncpg compatibility
        placeholders = ",".join([f":id_{i}" for i in range(len(session_ids))])
        params = {f"id_{i}": sid for i, sid in enumerate(session_ids)}

        query = f"""
            SELECT
                session_id,
                feedback_type
            FROM chat_sessions
            WHERE session_id IN ({placeholders})
        """

        try:
            logger.log_db_operation(query, params)
            
            db_start = time.time()
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                rows = result.fetchall()
            db_duration = time.time() - db_start
            
            logger.log_db_query(query, params, rows)

            # Build result dictionary
            result_dict = {}
            for row in rows:
                row_dict = dict(row._mapping)
                session_id = row_dict['session_id']
                feedback_type = row_dict.get('feedback_type')
                
                result_dict[session_id] = {
                    "positive_count": 1 if feedback_type == 'positive' else 0,
                    "negative_count": 1 if feedback_type == 'negative' else 0
                }

            # Fill in missing sessions with zero counts
            for session_id in session_ids:
                if session_id not in result_dict:
                    result_dict[session_id] = {"positive_count": 0, "negative_count": 0}

            logger.info(f"⏱️ [CHATLOG-DAO] Fetched feedback for {len(result_dict)} sessions in {db_duration:.2f}s (total: {time.time() - start_time:.2f}s)")
            return result_dict
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            # Return empty counts for all sessions on error
            return {sid: {"positive_count": 0, "negative_count": 0} for sid in session_ids}

    async def get_hil_enabled(self) -> bool:
        """Get HIL enabled status from security_settings."""
        # Read from security_settings where HIL is now persisted
        query = "SELECT setting_value FROM security_settings WHERE setting_name = 'hil_enabled' LIMIT 1"

        try:
            logger.log_db_operation(query)
            async with get_db_session() as session:
                result = await session.execute(text(query))
                row = result.fetchone()
                logger.log_db_query(query, None, row)
                if row:
                    # Convert tuple/Row to dict for consistent access
                    row_dict = dict(row._mapping) if hasattr(row, '_mapping') else {'setting_value': row[0]}

                    # Handle any boolean representation from database
                    hil_value = row_dict.get('setting_value', 'true')
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

    async def mark_session_as_read(self, session_id: int) -> bool:
        """Mark entire session as read (session-level, not per-message)."""
        query = "UPDATE chat_sessions SET is_session_read = true, updated_at = NOW() WHERE id = :session_id"
        try:
            params = {"session_id": session_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                rows_updated = result.rowcount
                if rows_updated > 0:
                    logger.info(f"✅ Marked session {session_id} as read ({rows_updated} rows updated)")
                    logger.log_db_query(query, params, f"Updated {rows_updated} rows")
                    return True
                else:
                    logger.warning(f"⚠️ No rows updated for session {session_id} - session may not exist")
                    logger.log_db_query(query, params, f"Updated {rows_updated} rows")
                    return False
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            logger.error(f"❌ Failed to mark session {session_id} as read: {e}")
            return False

    async def mark_session_as_unread(self, session_id: int) -> bool:
        """Mark entire session as unread (session-level)."""
        query = "UPDATE chat_sessions SET is_session_read = false, updated_at = NOW() WHERE id = :session_id"
        try:
            params = {"session_id": session_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                rows_updated = result.rowcount
                if rows_updated > 0:
                    logger.info(f"✅ Marked session {session_id} as unread ({rows_updated} rows updated)")
                    logger.log_db_query(query, params, f"Updated {rows_updated} rows")
                    return True
                else:
                    logger.warning(f"⚠️ No rows updated for session {session_id} - session may not exist")
                    logger.log_db_query(query, params, f"Updated {rows_updated} rows")
                    return False
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            logger.error(f"❌ Failed to mark session {session_id} as unread: {e}")
            return False

    async def is_session_read(self, session_id: int) -> bool:
        """Check if session is read."""
        query = "SELECT is_session_read FROM chat_sessions WHERE id = :session_id"
        try:
            params = {"session_id": session_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                if row:
                    is_read = row[0]
                    # Handle both Python bool and PostgreSQL text bool representation
                    if isinstance(is_read, bool):
                        return is_read
                    if isinstance(is_read, str):
                        return is_read.lower() in ('true', 't', '1', 'yes')
                    return bool(is_read)
                return False
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False
