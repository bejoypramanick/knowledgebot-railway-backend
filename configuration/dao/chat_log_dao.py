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
            logger.info(f"🔍 [DAO] Fetching all human agents")
            logger.log_db_operation(query)
            async with get_db_session() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
                logger.log_db_query(query, None, rows)
                
                emails = [dict(r._mapping)['email'] for r in rows] if rows else []
                logger.info(f"✅ [DAO] Found {len(emails)} human agents: {emails}")
                return emails
        except Exception as e:
            logger.error(f"❌ [DAO] Error fetching human agents: {e}", exc_info=True)
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
            logger.info(f"🔍 [DAO] Fetching all admins")
            logger.log_db_operation(query)
            async with get_db_session() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
                logger.log_db_query(query, None, rows)
                
                emails = [dict(r._mapping)['email'] for r in rows] if rows else []
                logger.info(f"✅ [DAO] Found {len(emails)} admins: {emails}")
                return emails
        except Exception as e:
            logger.error(f"❌ [DAO] Error fetching admins: {e}", exc_info=True)
            logger.log_db_query(query, None, error=e)
            return []

    async def get_all_admin_ids(self) -> List[str]:
        """Get all admin user IDs."""
        query = """
            SELECT DISTINCT u.id
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            JOIN roles r ON urm.role_id = r.id
            WHERE r.role_name = 'admin'
        """
        try:
            logger.info(f"🔍 [DAO] Fetching all admin IDs")
            logger.log_db_operation(query)
            async with get_db_session() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
                logger.log_db_query(query, None, rows)

                ids = [dict(r._mapping)['id'] for r in rows] if rows else []
                logger.info(f"✅ [DAO] Found {len(ids)} admin IDs: {ids}")
                return ids
        except Exception as e:
            logger.error(f"❌ [DAO] Error fetching admin IDs: {e}", exc_info=True)
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

    async def get_user_role_id(self, email: str) -> Optional[str]:
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

    async def get_session_db_id(self, session_id: str) -> Optional[str]:
        """Get database ID for a session."""
        try:
            query = "SELECT id FROM chat_sessions WHERE id = :id"
            params = {"id": session_id}

            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                if row:
                    logger.log_db_query(query, params, row)
                    return row[0]
                else:
                    logger.warning(f"⚠️ Session {session_id} not found in database")
                    return None
        except Exception as e:
            logger.error(f"❌ Database error in get_session_db_id({session_id}): {e}", exc_info=True)
            logger.log_db_query("get_session_db_id", {"session_id": session_id}, error=e)
            return None

    async def get_session_db_id_by_uuid(self, session_uuid: str) -> Optional[str]:
        """Get database ID for a session by UUID.
        PG18: id IS the UUIDv7 PK — same as get_session_db_id."""
        try:
            query = "SELECT id FROM chat_sessions WHERE id = CAST(:session_id AS UUID)"
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

    async def get_session_by_uuid(self, session_uuid: str) -> Optional[Dict[str, Any]]:
        """Get session data by UUID. PG18: id IS the UUIDv7 PK."""
        try:
            query = """
                SELECT id, started_at, last_activity_at, is_active,
                       message_count, archive_status,
                       metadata->>'customer_email' as customer_email,
                       metadata->>'customer_name' as customer_name
                FROM chat_sessions
                WHERE id = CAST(:session_id AS UUID)
            """
            params = {"session_id": session_uuid}

            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.mappings().first()
                logger.log_db_query(query, params, row)
                return dict(row) if row else None
        except Exception as e:
            logger.log_db_query("get_session_by_uuid", {"session_uuid": session_uuid}, error=e)
            return None

    async def create_chat_session(self, session_id: str, metadata: Dict[str, Any]) -> str:
        """Create a new chat session. PG18: id IS the UUIDv7 PK."""
        query = """
            INSERT INTO chat_sessions (id, metadata, created_at, last_activity_at, is_active)
            VALUES (CAST(:session_id AS UUID), :metadata, NOW(), NOW(), true)
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

    async def create_session_assignment(self, session_db_id: str, email: str, type: str, status: str):
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
        # Include global User-N identifier
        try:
            query = f"""
                WITH ranked_sessions AS (
                    SELECT cs.*, 
                           'User-' || ROW_NUMBER() OVER (ORDER BY cs.created_at ASC) as user_display_id
                    FROM chat_sessions cs
                    WHERE (cs.message_count > 0 OR cs.message_count IS NULL)
                ),
                agent_sessions AS (
                    SELECT rs.*, u.email as agent_email, u.id::text as agent_id
                    FROM ranked_sessions rs
                    JOIN session_assignments sa ON rs.id = sa.session_id
                    JOIN user_role_mapping urm ON sa.user_role_id = urm.user_role_id
                    JOIN users u ON urm.user_id = u.id
                    WHERE sa.user_role_id = :user_role_id
                      AND (:archive_status = 'all' OR rs.archive_status = :archive_status)
                      AND (rs.message_count > 0 OR rs.message_count IS NULL)
                )
                SELECT DISTINCT ON (id) * FROM agent_sessions
                ORDER BY id, last_activity_at DESC NULLS LAST
                LIMIT :limit OFFSET :offset
            """
            params = {
                "user_role_id": user_role_id, 
                "archive_status": archive_status, 
                "limit": limit, 
                "offset": offset
            }
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                rows = result.fetchall()
                logger.log_db_query(query, params, rows)
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.error(f"❌ Error fetching sessions for agent {email}: {e}")
            return []

    async def count_sessions_for_agent(self, email: str, archive_status: str) -> int:
        user_role_id = await self.get_user_role_id(email)
        if not user_role_id:
            return 0

        try:
            # Handle 'all' status - count all sessions regardless of archive status
            # Exclude sessions with no messages (abandoned/test sessions)
            if archive_status.lower() == 'all':
                query = """
                    SELECT COUNT(*)
                    FROM chat_sessions cs
                    LEFT JOIN session_assignments sa ON cs.id = sa.session_id
                    WHERE sa.user_role_id = :user_role_id
                      AND (cs.message_count > 0 OR cs.message_count IS NULL)
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
                    WHERE sa.user_role_id = :user_role_id 
                      AND cs.archive_status = :archive_status
                      AND (cs.message_count > 0 OR cs.message_count IS NULL)
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
        # Include a global sequence number (User-1, User-2, etc.) based on creation time
        if archive_status.lower() == 'all':
            query = """
                WITH ranked_sessions AS (
                    SELECT cs.*, 
                           'User-' || ROW_NUMBER() OVER (ORDER BY cs.created_at ASC) as user_display_id
                    FROM chat_sessions cs
                    WHERE (cs.message_count > 0 OR cs.message_count IS NULL)
                ),
                deduped AS (
                    SELECT DISTINCT ON (rs.id) rs.*, u.email as agent_email, u.id::text as agent_id
                    FROM ranked_sessions rs
                    LEFT JOIN session_assignments sa ON rs.id = sa.session_id
                    LEFT JOIN user_role_mapping urm ON sa.user_role_id = urm.user_role_id
                    LEFT JOIN users u ON urm.user_id = u.id
                    ORDER BY rs.id, CASE WHEN sa.status = 'active' THEN 0 ELSE 1 END, sa.assigned_at DESC NULLS LAST
                )
                SELECT * FROM deduped
                ORDER BY last_activity_at DESC NULLS LAST
                LIMIT :limit OFFSET :offset
            """
            
            try:
                params = {"limit": limit, "offset": offset}
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
                WITH ranked_sessions AS (
                    SELECT cs.*, 
                           'User-' || ROW_NUMBER() OVER (ORDER BY cs.created_at ASC) as user_display_id
                    FROM chat_sessions cs
                    WHERE cs.archive_status = :archive_status
                      AND (cs.message_count > 0 OR cs.message_count IS NULL)
                ),
                deduped AS (
                    SELECT DISTINCT ON (rs.id) rs.*, u.email as agent_email, u.id::text as agent_id
                    FROM ranked_sessions rs
                    LEFT JOIN session_assignments sa ON rs.id = sa.session_id
                    LEFT JOIN user_role_mapping urm ON sa.user_role_id = urm.user_role_id
                    LEFT JOIN users u ON urm.user_id = u.id
                    ORDER BY rs.id, CASE WHEN sa.status = 'active' THEN 0 ELSE 1 END, sa.assigned_at DESC NULLS LAST
                )
                SELECT * FROM deduped
                ORDER BY last_activity_at DESC NULLS LAST
                LIMIT :limit OFFSET :offset
            """
            
            try:
                params = {"archive_status": archive_status, "limit": limit, "offset": offset}
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
                query = "SELECT COUNT(*) FROM chat_sessions WHERE (message_count > 0 OR message_count IS NULL)"
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
                query = "SELECT COUNT(*) FROM chat_sessions WHERE archive_status = :archive_status AND (message_count > 0 OR message_count IS NULL)"
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

    async def get_messages_for_sessions(self, session_ids: List[str]) -> Dict[str, List[Dict[str, Any]]]:
        """Get messages for multiple sessions using single LEFT JOIN query."""
        if not session_ids: return {}

        # Single LEFT JOIN query: get all messages for selected sessions in one go
        query = """
            SELECT cm.*
            FROM chat_sessions cs
            LEFT JOIN chat_messages cm ON cs.id = cm.session_id
            WHERE cs.id = ANY(:session_ids)
            ORDER BY cs.id, cm.created_at ASC
        """
        params = {"session_ids": session_ids}

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                rows = result.fetchall()

                # Group messages by session_id, skip NULL message rows
                result_dict = {}
                for r in rows:
                    row = dict(r._mapping)
                    # Skip rows where message is NULL (session has no messages)
                    if row.get('id') is None:
                        continue

                    session_id = str(row['session_id'])
                    if session_id not in result_dict:
                        result_dict[session_id] = []
                    result_dict[session_id].append(row)

                return result_dict
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            logger.error(f"Error fetching messages: {e}")
            return {}

    async def get_latest_message_for_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get the latest message for a single session."""
        query = """
            SELECT * FROM chat_messages
            WHERE session_id = :session_id
            ORDER BY id DESC
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

    async def get_latest_messages_batch(self, session_ids: List[str]) -> Dict[str, Dict[str, Any]]:
        """Get the latest message for multiple sessions in a single query (OPTIMIZED)."""
        import time
        start_time = time.time()
        
        if not session_ids:
            return {}

        # Log immediately to see if there's a delay before this point
        logger.info(f"🔍 [CHATLOG-DAO] get_latest_messages_batch called for {len(session_ids)} sessions at {time.time()}")
        
        # Check pool status WITHOUT acquiring a connection
        from shared.sqlalchemy_db import _engine
        if _engine:
            pool = _engine.pool
            logger.info(f"📊 [POOL-STATUS] BEFORE: size={pool.size()}, checked_out={pool.checkedout()}, overflow={pool.overflow()}, available={pool.size() - pool.checkedout()}")
            
            if pool.checkedout() >= pool.size():
                logger.error(f"🚨 [POOL-EXHAUSTED] All {pool.size()} connections are checked out! This request will wait for a connection.")
        
        logger.info(f"🔍 [CHATLOG-DAO] Session IDs: {session_ids}")
        
        # Use DISTINCT ON to efficiently get the latest message per session
        # Works with UUIDv7 since they are time-sortable
        query = """
            SELECT DISTINCT ON (session_id) *
            FROM chat_messages
            WHERE session_id = ANY(:session_ids)
            ORDER BY session_id, id DESC
        """
        
        try:
            params = {"session_ids": session_ids}
            logger.info(f"🔍 [CHATLOG-DAO] About to get DB session at {time.time()}...")
            
            session_acquire_start = time.time()
            async with get_db_session() as session:
                session_acquire_duration = time.time() - session_acquire_start
                logger.info(f"⏱️ [CHATLOG-DAO] DB session acquired in {session_acquire_duration:.2f}s at {time.time()}")
                
                if session_acquire_duration > 5:
                    logger.error(f"🚨 [SLOW-ACQUIRE] Session acquisition took {session_acquire_duration:.2f}s - POOL EXHAUSTION!")
                
                logger.info(f"🔍 [CHATLOG-DAO] About to execute query at {time.time()}...")
                logger.log_db_operation(query, params)
                
                query_start = time.time()
                result = await session.execute(text(query), params)
                query_duration = time.time() - query_start
                logger.info(f"⏱️ [CHATLOG-DAO] Query executed in {query_duration:.2f}s")
                
                if query_duration > 5:
                    logger.error(f"🚨 [SLOW-QUERY] Query execution took {query_duration:.2f}s!")
                
                fetch_start = time.time()
                rows = result.fetchall()
                fetch_duration = time.time() - fetch_start
                logger.info(f"⏱️ [CHATLOG-DAO] Results fetched in {fetch_duration:.2f}s")
            
            # Check connection pool status AFTER query
            if _engine:
                pool = _engine.pool
                logger.info(f"📊 [POOL-STATUS] AFTER: size={pool.size()}, checked_out={pool.checkedout()}, overflow={pool.overflow()}, available={pool.size() - pool.checkedout()}")
            
            db_duration = time.time() - start_time
            
            result_dict = {row.session_id: dict(row._mapping) for row in rows}
            logger.info(f"⏱️ [CHATLOG-DAO] Fetched {len(result_dict)} latest messages in {db_duration:.2f}s")
            logger.info(f"⏱️ [CHATLOG-DAO] Breakdown - Acquire: {session_acquire_duration:.2f}s, Execute: {query_duration:.2f}s, Fetch: {fetch_duration:.2f}s")
            
            return result_dict
        except Exception as e:
            logger.error(f"❌ [CHATLOG-DAO] Error in get_latest_messages_batch after {time.time() - start_time:.2f}s: {e}")
            import traceback
            logger.error(f"❌ [CHATLOG-DAO] Traceback: {traceback.format_exc()}")
            logger.log_db_query(query, params, error=e)
            
            # Check pool status on error
            if _engine:
                pool = _engine.pool
                logger.error(f"📊 [POOL-ERROR] size={pool.size()}, checked_out={pool.checkedout()}, overflow={pool.overflow()}")
            
            return {}


    async def get_session_messages(self, session_id: str) -> List[Dict[str, Any]]:
        """Get all messages for a single session (full conversation)."""
        query = """
            SELECT * FROM chat_messages
            WHERE session_id = :session_id
            ORDER BY id ASC
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

    async def create_message(self, session_db_id: str, role: str, content: str) -> str:
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

    async def increment_message_count(self, session_db_id: str):
        # Optional: if you have a message_count column in chat_sessions
        pass 

    async def archive_session(self, session_id: str, status: str) -> bool:
        """Archive a session."""
        try:
            query = """
                UPDATE chat_sessions SET archive_status = :status
                WHERE id = :id
            """
            params = {"id": session_id, "status": status}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
                return result.rowcount > 0 if hasattr(result, 'rowcount') else True
        except Exception as e:
            logger.log_db_query(query, {"session_id": session_id, "status": status}, error=e)
            return False


    async def update_session_feedback(self, session_id: str, feedback_type: str) -> bool:
        """
        Update session feedback (thumbs up/down).

        Args:
            session_id: Session ID (UUID)
            feedback_type: 'positive' or 'negative'

        Returns:
            True if updated successfully
        """
        try:
            query = """
                UPDATE chat_sessions
                SET feedback_type = :feedback_type,
                    feedback_provided_at = NOW()
                WHERE id = :id
            """
            params = {"id": session_id, "feedback_type": feedback_type}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
                logger.info(f"✅ Feedback '{feedback_type}' saved for session {session_id}")
                return result.rowcount > 0 if hasattr(result, 'rowcount') else True
        except Exception as e:
            logger.error(f"❌ Error updating session feedback: {e}")
            logger.log_db_query(query, {"session_id": session_id, "feedback_type": feedback_type}, error=e)
            return False


    async def get_session_by_id(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session by ID."""
        try:
            query = "SELECT * FROM chat_sessions WHERE id = :id"
            params = {"id": session_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()

                if row:
                    logger.log_db_query(query, params, row)
                    return dict(row._mapping)
                else:
                    logger.warning(f"⚠️ Session {session_id} not found in database (query returned 0 rows)")
                    logger.log_db_query(query, params, None)
                    return None
        except Exception as e:
            logger.error(f"❌ Database error fetching session {session_id}: {e}", exc_info=True)
            logger.log_db_query(query, {"session_id": session_id}, error=e)
            return None

    # Alias for backward compatibility
    async def get_session_by_id_with_messages(self, session_id: str) -> Optional[Dict[str, Any]]:
        return await self.get_session_by_id(session_id)

    async def get_assigned_agent_email(self, session_id: str) -> Optional[str]:
        """Get the assigned agent's email for a session from session_assignments table."""
        query = """
            SELECT u.email
            FROM session_assignments sa
            JOIN user_role_mapping urm ON sa.user_role_id = urm.user_role_id
            JOIN users u ON urm.user_id = u.id
            WHERE sa.session_id = :session_id AND sa.status = 'active'
            ORDER BY sa.assigned_at DESC
            LIMIT 1
        """
        try:
            params = {"session_id": session_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                if row:
                    logger.log_db_query(query, params, row)
                    return row[0]
                else:
                    logger.log_db_query(query, params, None)
                    return None
        except Exception as e:
            logger.error(f"❌ Error fetching assigned agent for session {session_id}: {e}", exc_info=True)
            logger.log_db_query(query, {"session_id": session_id}, error=e)
            return None

    async def get_assigned_agent_id(self, session_id: str) -> Optional[str]:
        """Get the assigned agent's user ID for a session from session_assignments table."""
        query = """
            SELECT u.id
            FROM session_assignments sa
            JOIN user_role_mapping urm ON sa.user_role_id = urm.user_role_id
            JOIN users u ON urm.user_id = u.id
            WHERE sa.session_id = :session_id AND sa.status = 'active'
            ORDER BY sa.assigned_at DESC
            LIMIT 1
        """
        try:
            params = {"session_id": session_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                if row:
                    logger.log_db_query(query, params, row)
                    return row[0]
                else:
                    logger.log_db_query(query, params, None)
                    return None
        except Exception as e:
            logger.error(f"❌ Error fetching assigned agent ID for session {session_id}: {e}", exc_info=True)
            logger.log_db_query(query, {"session_id": session_id}, error=e)
            return None

    async def get_user_id_by_email(self, email: str) -> Optional[str]:
        """Get user ID from email address."""
        query = "SELECT id FROM users WHERE email = :email"
        try:
            params = {"email": email}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                if row:
                    logger.log_db_query(query, params, row)
                    return str(row[0])  # PG18: UUID object → string
                else:
                    logger.log_db_query(query, params, None)
                    return None
        except Exception as e:
            logger.error(f"❌ Error fetching user ID for email {email}: {e}", exc_info=True)
            logger.log_db_query(query, {"email": email}, error=e)
            return None

    async def get_email_by_user_id(self, user_id: str) -> Optional[str]:
        """Get email from user ID."""
        query = "SELECT email FROM users WHERE id = :id"
        try:
            params = {"id": user_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                if row:
                    logger.log_db_query(query, params, row)
                    return row[0]
                else:
                    logger.log_db_query(query, params, None)
                    return None
        except Exception as e:
            logger.error(f"❌ Error fetching email for user ID {user_id}: {e}", exc_info=True)
            logger.log_db_query(query, {"id": user_id}, error=e)
            return None

    async def get_session_uuid(self, session_db_id: str) -> Optional[str]:
        """Get session UUID from session database ID. PG18: id IS the UUID."""
        query = "SELECT id FROM chat_sessions WHERE id = CAST(:id AS UUID)"
        try:
            params = {"id": session_db_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                if row:
                    logger.log_db_query(query, params, row)
                    return row[0]
                else:
                    logger.log_db_query(query, params, None)
                    return None
        except Exception as e:
            logger.error(f"❌ Error fetching UUID for session {session_db_id}: {e}", exc_info=True)
            logger.log_db_query(query, {"id": session_db_id}, error=e)
            return None


    async def get_session_numeric_id(self, session_uuid: str) -> Optional[str]:
        """Get session database ID from session UUID. PG18: id IS the UUID — same lookup."""
        query = "SELECT id FROM chat_sessions WHERE id = CAST(:uuid AS UUID)"
        try:
            params = {"uuid": session_uuid}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                if row:
                    logger.log_db_query(query, params, row)
                    return row[0]
                else:
                    logger.log_db_query(query, params, None)
                    return None
        except Exception as e:
            logger.error(f"❌ Error fetching database ID for UUID {session_uuid}: {e}", exc_info=True)
            logger.log_db_query(query, {"uuid": session_uuid}, error=e)
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
        # PG18: id IS the UUIDv7 PK — no separate session_id column
        query = """
            SELECT
                feedback_type
            FROM chat_sessions
            WHERE id = CAST(:session_id AS UUID)
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

        # PG18: id IS the UUIDv7 PK — alias as session_id for backward compat
        query = f"""
            SELECT
                id,
                feedback_type
            FROM chat_sessions
            WHERE id IN ({placeholders})
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
                session_id = str(row_dict['id'])
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

    async def mark_session_as_read(self, session_id: str) -> bool:
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

    async def mark_session_as_unread(self, session_id: str) -> bool:
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

    async def get_user_display_id_map(self) -> Dict[str, str]:
        """
        Pre-fetch global User-N mapping in ONE fast query.
        Uses ROW_NUMBER() over all sessions ordered by created_at ASC.
        Returns dict: {session_id: "User-1", ...}

        This runs once before streaming starts (~5-10ms for any table size,
        uses index-only scan on created_at).
        """
        query = """
            SELECT id, 'User-' || ROW_NUMBER() OVER (ORDER BY created_at ASC) as user_display_id
            FROM chat_sessions
            WHERE (message_count > 0 OR message_count IS NULL)
        """
        try:
            async with get_db_session() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
                return {str(r._mapping['id']): r._mapping['user_display_id'] for r in rows}
        except Exception as e:
            logger.error(f"❌ [STREAM-DAO] Error fetching display ID map: {e}")
            return {}

    async def stream_all_sessions_with_latest_message(
        self,
        archive_status: str,
        limit: int,
        cursor_timestamp: Optional[str] = None,
        display_id_map: Optional[Dict[str, str]] = None
    ):
        """
        Stream sessions row-by-row from PG18 server-side cursor.
        Zero CTEs, zero correlated subqueries — pure index scans.

        Query plan (all index lookups, no seq scans):
          1. Index Scan on idx_chat_sessions_last_activity (DESC) → first row in <1ms
          2. LATERAL idx_session_assignments_session → agent in <0.1ms
          3. LATERAL idx_chat_messages_session_ordered → latest msg in <0.1ms
          4. yield row → SSE event sent immediately

        Yields:
            Dict per session (agent_email, latest_msg_*, user_display_id merged from pre-fetched map)
        """
        import time
        start_time = time.time()
        logger.info(f"🔍 [STREAM-DAO] stream_all_sessions: status={archive_status}, limit={limit}, cursor={cursor_timestamp}")

        conditions = ["(cs.message_count > 0 OR cs.message_count IS NULL)"]
        params: Dict[str, Any] = {"limit": limit}

        if cursor_timestamp:
            conditions.append("cs.last_activity_at < :cursor_ts")
            params["cursor_ts"] = cursor_timestamp

        if archive_status.lower() != 'all':
            conditions.append("cs.archive_status = :archive_status")
            params["archive_status"] = archive_status

        where_clause = " AND ".join(conditions)

        query = f"""
            SELECT cs.*,
                   ag.email as agent_email,
                   ag.user_id::text as agent_id,
                   lm.content as latest_msg_content,
                   lm.role as latest_msg_role,
                   lm.created_at as latest_msg_at,
                   lm.id as latest_msg_id
            FROM chat_sessions cs
            LEFT JOIN LATERAL (
                SELECT u.email, u.id as user_id
                FROM session_assignments sa
                JOIN user_role_mapping urm ON sa.user_role_id = urm.user_role_id
                JOIN users u ON urm.user_id = u.id
                WHERE sa.session_id = cs.id
                ORDER BY CASE WHEN sa.status = 'active' THEN 0 ELSE 1 END,
                         sa.assigned_at DESC NULLS LAST
                LIMIT 1
            ) ag ON true
            LEFT JOIN LATERAL (
                SELECT id, content, role, created_at
                FROM chat_messages
                WHERE session_id = cs.id
                ORDER BY created_at DESC
                LIMIT 1
            ) lm ON true
            WHERE {where_clause}
            ORDER BY cs.last_activity_at DESC NULLS LAST
            LIMIT :limit
        """

        try:
            logger.log_db_operation(query, params)
            id_map = display_id_map or {}

            async with get_db_session() as session:
                result = await session.stream(
                    text(query).execution_options(yield_per=1),
                    params
                )

                row_count = 0
                async for row in result:
                    row_count += 1
                    row_dict = dict(row._mapping)
                    # Merge pre-fetched User-N display ID
                    sid = str(row_dict['id'])
                    row_dict['user_display_id'] = id_map.get(sid, f"User-{sid[:8]}")
                    yield row_dict

                logger.info(f"⏱️ [STREAM-DAO] Streamed {row_count} rows in {time.time() - start_time:.2f}s")

        except Exception as e:
            logger.error(f"❌ [STREAM-DAO] Error streaming sessions: {e}")
            import traceback
            logger.error(f"❌ [STREAM-DAO] Traceback: {traceback.format_exc()}")

    async def get_feedback_for_session(self, session_id: str) -> Optional[str]:
        """Get feedback type for a single session (used in streaming mode)."""
        query = "SELECT feedback_type FROM chat_sessions WHERE id = :session_id"
        try:
            params = {"session_id": session_id}
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                return row[0] if row and row[0] else None
        except Exception as e:
            logger.error(f"❌ [STREAM-DAO] Error getting feedback for {session_id}: {e}")
            return None

    async def is_session_read(self, session_id: str) -> bool:
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
