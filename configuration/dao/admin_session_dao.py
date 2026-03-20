"""
Admin Session Data Access Object
Handles database operations for admin session tracking and management
"""

from typing import Any, Dict, List, Optional
from datetime import datetime

from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("admin_session_dao", "configuration")


class AdminSessionDAO:
    """DAO for admin session management"""

    def __init__(self):
        pass

    async def create_session(
        self,
        session_id: str,
        user_role_id: int,
        email: str,
        role_name: str,
        ip_address: Optional[str],
        user_agent: Optional[str],
        browser: Optional[str],
        os: Optional[str],
        device_type: Optional[str],
        expires_at: datetime,
    ) -> Optional[Dict[str, Any]]:
        """Create a new admin session."""
        query = """
            INSERT INTO admin_sessions (
                session_id, user_role_id, email, role_name,
                ip_address, user_agent, browser, os, device_type,
                expires_at, is_active, login_at, last_activity_at
            ) VALUES (:session_id, :user_role_id, :email, :role_name, :ip_address, :user_agent, :browser, :os, :device_type, :expires_at, true, :now, :now)
            RETURNING id, session_id, email, role_name, login_at, is_active
        """

        now = datetime.utcnow()
        params = {
            "session_id": session_id,
            "user_role_id": user_role_id,
            "email": email,
            "role_name": role_name,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "browser": browser,
            "os": os,
            "device_type": device_type,
            "expires_at": expires_at,
            "now": now,
        }

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                logger.log_db_query(query, params, row)
                await session.commit()
                return dict(row._mapping) if row else None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def get_session(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get a session by session_id."""
        query = """
            SELECT id, session_id, user_role_id, email, role_name,
                   ip_address, user_agent, browser, os, device_type,
                   login_at, logout_at, last_activity_at, expires_at,
                   is_active, logout_reason, action_count, metadata
            FROM admin_sessions
            WHERE session_id = :session_id
        """

        try:
            logger.log_db_operation(query, session_id)
            async with get_db_session() as session:
                result = await session.execute(text(query), {"session_id": session_id})
                row = result.fetchone()
                logger.log_db_query(query, session_id, row)
                return dict(row._mapping) if row else None
        except Exception as e:
            logger.log_db_query(query, session_id, error=e)
            return None

    async def get_active_sessions(self, email: Optional[str] = None) -> List[Dict[str, Any]]:
        """Get all active sessions, optionally filtered by email."""
        if email:
            query = """
                SELECT id, session_id, email, role_name, ip_address, browser, os, device_type,
                       login_at, last_activity_at, expires_at, is_active, action_count
                FROM admin_sessions
                WHERE email = :email AND is_active = true
                ORDER BY id DESC
            """
            params = {"email": email}
        else:
            query = """
                SELECT id, session_id, email, role_name, ip_address, browser, os, device_type,
                       login_at, last_activity_at, expires_at, is_active, action_count
                FROM admin_sessions
                WHERE is_active = true
                ORDER BY id DESC
            """
            params = {}

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                results = result.fetchall()
                logger.log_db_query(query, params, results)
                return [dict(row._mapping) for row in results]
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return []

    async def update_last_activity(self, session_id: str) -> bool:
        """Update last_activity_at for a session."""
        query = """
            UPDATE admin_sessions
            SET last_activity_at = :now
            WHERE session_id = :session_id
        """

        now = datetime.utcnow()
        params = {"now": now, "session_id": session_id}

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
                return True
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False

    async def logout_session(self, session_id: str, reason: str = "manual") -> bool:
        """Logout a session by marking it inactive. PG18: RETURNING OLD/NEW for atomic audit."""
        query = """
            UPDATE admin_sessions
            SET is_active = false, logout_at = :now, logout_reason = :reason
            WHERE session_id = :session_id
            RETURNING OLD.is_active AS was_active, OLD.action_count AS final_action_count,
                      NEW.logout_at AS logout_at, NEW.logout_reason AS logout_reason
        """

        now = datetime.utcnow()
        params = {"now": now, "reason": reason, "session_id": session_id}

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                await session.commit()
                if row:
                    change = dict(row._mapping)
                    logger.info(f"Session {session_id} logged out: was_active={change.get('was_active')}, "
                               f"actions={change.get('final_action_count')}, reason={change.get('logout_reason')}")
                logger.log_db_query(query, params, row)
                return True
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False

    async def expire_old_sessions(self) -> int:
        """Mark expired sessions as inactive. PG18: RETURNING OLD/NEW for audit log."""
        query = """
            UPDATE admin_sessions
            SET is_active = false, logout_reason = 'expired'
            WHERE is_active = true AND expires_at < NOW()
            RETURNING OLD.session_id AS session_id, OLD.email AS email,
                      OLD.expires_at AS expired_at, OLD.action_count AS action_count
        """

        try:
            logger.log_db_operation(query)
            async with get_db_session() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
                await session.commit()
                count = len(rows)
                if count > 0:
                    for row in rows:
                        change = dict(row._mapping)
                        logger.info(f"Expired session {change.get('session_id')} "
                                   f"(email={change.get('email')}, actions={change.get('action_count')})")
                logger.log_db_query(query, result=None)
                return count
        except Exception as e:
            logger.log_db_query(query, error=e)
            return 0

    async def get_session_analytics(self, days: int = 30) -> Dict[str, Any]:
        """Get session analytics for the last N days."""
        query = """
            SELECT
                COUNT(*) as total_sessions,
                COUNT(DISTINCT email) as unique_users,
                COUNT(*) FILTER (WHERE is_active = true) as active_sessions,
                AVG(EXTRACT(EPOCH FROM (COALESCE(logout_at, CURRENT_TIMESTAMP) - login_at))) as avg_duration_seconds
            FROM admin_sessions
            WHERE login_at > NOW() - INTERVAL '1 day' * :days
        """

        params = {"days": days}

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                logger.log_db_query(query, params, row)
                return dict(row._mapping) if row else {}
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return {}

    async def cleanup_old_sessions(self, days: int = 90) -> int:
        """Delete sessions older than N days. Returns count of deleted sessions."""
        query = """
            DELETE FROM admin_sessions
            WHERE login_at < NOW() - INTERVAL '1 day' * :days
        """

        params = {"days": days}

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
                # Get the count of rows affected
                count = result.rowcount if hasattr(result, 'rowcount') else 0
                return count
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return 0
