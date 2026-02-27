"""
Admin Action Data Access Object
Handles database operations for action audit trail and analytics
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("admin_action_dao", "configuration")


class AdminActionDAO:
    """DAO for admin action audit logging and queries"""

    def __init__(self):
        pass

    async def get_actions(
        self,
        email: Optional[str] = None,
        category: Optional[str] = None,
        success: Optional[bool] = None,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Get actions with optional filters."""
        query = """
            SELECT
                id, action_id, session_id, user_role_id, email, role_name,
                action_type, action_category, http_method, endpoint,
                resource_type, resource_id, duration_ms, success,
                error_message, error_code, response_status,
                ip_address, user_agent, created_at
            FROM admin_actions
            WHERE 1=1
        """

        params = []
        param_count = 0

        if email:
            param_count += 1
            query += f" AND email = ${param_count}"
            params.append(email)

        if category:
            param_count += 1
            query += f" AND action_category = ${param_count}"
            params.append(category)

        if success is not None:
            param_count += 1
            query += f" AND success = ${param_count}"
            params.append(success)

        query += f" ORDER BY created_at DESC LIMIT ${param_count + 1} OFFSET ${param_count + 2}"
        params.extend([limit, offset])

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                results = await conn.fetch(query, *params)
                logger.log_db_query(query, params, results)
                return [dict(row) for row in results]
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return []

    async def get_action_statistics(self, days: int = 7) -> Dict[str, Any]:
        """Get action statistics by category for the last N days."""
        query = """
            SELECT
                action_category,
                COUNT(*) as total_actions,
                COUNT(*) FILTER (WHERE success = true) as successful_actions,
                COUNT(*) FILTER (WHERE success = false) as failed_actions,
                ROUND(100.0 * COUNT(*) FILTER (WHERE success = true) / COUNT(*), 2) as success_rate_percent,
                ROUND(AVG(COALESCE(duration_ms, 0)), 2) as avg_duration_ms,
                MAX(COALESCE(duration_ms, 0)) as max_duration_ms,
                MIN(COALESCE(duration_ms, 0)) as min_duration_ms
            FROM admin_actions
            WHERE created_at > NOW() - INTERVAL '1 day' * $1
            GROUP BY action_category
            ORDER BY total_actions DESC
        """

        params = days

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                results = await conn.fetch(query, params)
                logger.log_db_query(query, params, results)
                return {
                    "statistics": [dict(row) for row in results],
                    "period_days": days,
                    "generated_at": datetime.utcnow().isoformat(),
                }
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return {"statistics": [], "period_days": days, "error": str(e)}

    async def get_failed_actions(
        self,
        days: int = 7,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get failed actions for monitoring/debugging."""
        query = """
            SELECT
                action_id, email, role_name, action_type, action_category,
                http_method, endpoint, error_message, error_code, duration_ms,
                created_at
            FROM admin_actions
            WHERE success = false
              AND created_at > NOW() - INTERVAL '1 day' * $1
            ORDER BY created_at DESC
            LIMIT $2
        """

        params = (days, limit)

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                results = await conn.fetch(query, *params)
                logger.log_db_query(query, params, results)
                return [dict(row) for row in results]
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return []

    async def get_user_actions(
        self,
        email: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Get all actions for a specific user."""
        query = """
            SELECT
                id, action_id, action_type, action_category, http_method,
                endpoint, resource_type, resource_id, success, duration_ms,
                created_at
            FROM admin_actions
            WHERE email = $1
            ORDER BY created_at DESC
            LIMIT $2 OFFSET $3
        """

        params = (email, limit, offset)

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                results = await conn.fetch(query, *params)
                logger.log_db_query(query, params, results)
                return [dict(row) for row in results]
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return []

    async def get_action_by_id(self, action_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific action by action_id."""
        query = """
            SELECT *
            FROM admin_actions
            WHERE action_id = $1
        """

        try:
            logger.log_db_operation(query, action_id)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, action_id)
                logger.log_db_query(query, action_id, result)
                return dict(result) if result else None
        except Exception as e:
            logger.log_db_query(query, action_id, error=e)
            return None

    async def cleanup_old_actions(self, days: int = 365) -> int:
        """Delete actions older than N days. Returns count of deleted actions."""
        query = """
            DELETE FROM admin_actions
            WHERE created_at < NOW() - INTERVAL '1 day' * $1
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
