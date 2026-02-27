"""
Admin Session Data Access Object
Handles database operations for admin session tracking and management
"""

from typing import Any, Dict, List, Optional
from datetime import datetime

from shared.db import get_db_connection
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
            ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, true, $11, $11)
            RETURNING id, session_id, email, role_name, login_at, is_active
        """

        now = datetime.utcnow()
        params = (
            session_id,
            user_role_id,
            email,
            role_name,
            ip_address,
            user_agent,
            browser,
            os,
            device_type,
            expires_at,
            now,
        )

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, *params)
                logger.log_db_query(query, params, result)
                return dict(result) if result else None
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
            WHERE session_id = $1
        """

        try:
            logger.log_db_operation(query, session_id)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, session_id)
                logger.log_db_query(query, session_id, result)
                return dict(result) if result else None
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
                WHERE email = $1 AND is_active = true
                ORDER BY login_at DESC
            """
            params = email
        else:
            query = """
                SELECT id, session_id, email, role_name, ip_address, browser, os, device_type,
                       login_at, last_activity_at, expires_at, is_active, action_count
                FROM admin_sessions
                WHERE is_active = true
                ORDER BY login_at DESC
            """
            params = None

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                if params:
                    results = await conn.fetch(query, params)
                else:
                    results = await conn.fetch(query)
                logger.log_db_query(query, params, results)
                return [dict(row) for row in results]
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return []

    async def update_last_activity(self, session_id: str) -> bool:
        """Update last_activity_at for a session."""
        query = """
            UPDATE admin_sessions
            SET last_activity_at = $1
            WHERE session_id = $2
        """

        now = datetime.utcnow()
        params = (now, session_id)

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, *params)
                logger.log_db_query(query, params, result)
                return True
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False

    async def logout_session(self, session_id: str, reason: str = "manual") -> bool:
        """Logout a session by marking it inactive."""
        query = """
            UPDATE admin_sessions
            SET is_active = false, logout_at = $1, logout_reason = $2
            WHERE session_id = $3
        """

        now = datetime.utcnow()
        params = (now, reason, session_id)

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, *params)
                logger.log_db_query(query, params, result)
                return True
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False

    async def expire_old_sessions(self) -> int:
        """Mark expired sessions as inactive. Returns count of updated sessions."""
        query = """
            UPDATE admin_sessions
            SET is_active = false, logout_reason = 'expired'
            WHERE is_active = true AND expires_at < NOW()
        """

        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.execute(query)
                logger.log_db_query(query, result=result)
                # Parse the result string "UPDATE n" to get count
                if isinstance(result, str) and result.startswith("UPDATE"):
                    try:
                        count = int(result.split()[-1])
                        return count
                    except (ValueError, IndexError):
                        return 0
                return 0
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
            WHERE login_at > NOW() - INTERVAL '1 day' * $1
        """

        params = days

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, params)
                logger.log_db_query(query, params, result)
                return dict(result) if result else {}
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return {}

    async def cleanup_old_sessions(self, days: int = 90) -> int:
        """Delete sessions older than N days. Returns count of deleted sessions."""
        query = """
            DELETE FROM admin_sessions
            WHERE login_at < NOW() - INTERVAL '1 day' * $1
        """

        params = days

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, params)
                logger.log_db_query(query, params, result)
                # Parse the result string "DELETE n" to get count
                if isinstance(result, str) and result.startswith("DELETE"):
                    try:
                        count = int(result.split()[-1])
                        return count
                    except (ValueError, IndexError):
                        return 0
                return 0
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return 0
