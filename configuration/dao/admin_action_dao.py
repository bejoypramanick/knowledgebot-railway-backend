"""
Admin Action Data Access Object
Handles database operations for action audit trail and analytics
"""

from typing import Any, Dict, List, Optional
from datetime import datetime, timedelta

from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
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
        where_clauses = ["1=1"]
        bind_params = {}

        if email:
            where_clauses.append("email = :email")
            bind_params['email'] = email

        if category:
            where_clauses.append("action_category = :category")
            bind_params['category'] = category

        if success is not None:
            where_clauses.append("success = :success")
            bind_params['success'] = success

        bind_params['limit'] = limit
        bind_params['offset'] = offset

        query_str = f"""
            SELECT
                id, action_id, session_id, user_role_id, email, role_name,
                action_type, action_category, http_method, endpoint,
                resource_type, resource_id, duration_ms, success,
                error_message, error_code, response_status,
                ip_address, user_agent, created_at
            FROM admin_actions
            WHERE {' AND '.join(where_clauses)}
            ORDER BY id DESC LIMIT :limit OFFSET :offset
        """
        query = text(query_str)

        try:
            logger.log_db_operation(query_str, bind_params)
            async with get_db_session() as session:
                results = await session.execute(query, bind_params)
                rows = results.fetchall()
                logger.log_db_query(query_str, bind_params, rows)
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.log_db_query(query_str, bind_params, error=e)
            return []

    async def get_action_statistics(self, days: int = 7) -> Dict[str, Any]:
        """Get action statistics by category for the last N days."""
        query = text("""
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
            WHERE created_at > NOW() - INTERVAL '1 day' * :days
            GROUP BY action_category
            ORDER BY total_actions DESC
        """)

        params = {"days": days}

        try:
            logger.log_db_operation(str(query), params)
            async with get_db_session() as session:
                results = await session.execute(query, params)
                rows = results.fetchall()
                logger.log_db_query(str(query), params, rows)
                return {
                    "statistics": [dict(row._mapping) for row in rows],
                    "period_days": days,
                    "generated_at": datetime.utcnow().isoformat(),
                }
        except Exception as e:
            logger.log_db_query(str(query), params, error=e)
            return {"statistics": [], "period_days": days, "error": str(e)}

    async def get_failed_actions(
        self,
        days: int = 7,
        limit: int = 50,
    ) -> List[Dict[str, Any]]:
        """Get failed actions for monitoring/debugging."""
        query = text("""
            SELECT
                action_id, email, role_name, action_type, action_category,
                http_method, endpoint, error_message, error_code, duration_ms,
                created_at
            FROM admin_actions
            WHERE success = false
              AND id >= (
                  SELECT COALESCE(MIN(id), '00000000-0000-0000-0000-000000000000'::uuid)
                  FROM admin_actions
                  WHERE created_at > NOW() - INTERVAL '1 day' * :days
              )
            ORDER BY id DESC
            LIMIT :limit
        """)

        params = {"days": days, "limit": limit}

        try:
            logger.log_db_operation(str(query), params)
            async with get_db_session() as session:
                results = await session.execute(query, params)
                rows = results.fetchall()
                logger.log_db_query(str(query), params, rows)
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.log_db_query(str(query), params, error=e)
            return []

    async def get_user_actions(
        self,
        email: str,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        """Get all actions for a specific user."""
        query = text("""
            SELECT
                id, action_id, action_type, action_category, http_method,
                endpoint, resource_type, resource_id, success, duration_ms,
                created_at
            FROM admin_actions
            WHERE email = :email
            ORDER BY id DESC
            LIMIT :limit OFFSET :offset
        """)

        params = {"email": email, "limit": limit, "offset": offset}

        try:
            logger.log_db_operation(str(query), params)
            async with get_db_session() as session:
                results = await session.execute(query, params)
                rows = results.fetchall()
                logger.log_db_query(str(query), params, rows)
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.log_db_query(str(query), params, error=e)
            return []

    async def get_action_by_id(self, action_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific action by action_id."""
        query = text("""
            SELECT *
            FROM admin_actions
            WHERE action_id = :action_id
        """)

        try:
            logger.log_db_operation(str(query), {"action_id": action_id})
            async with get_db_session() as session:
                result = await session.execute(query, {"action_id": action_id})
                row = result.fetchone()
                logger.log_db_query(str(query), {"action_id": action_id}, row)
                return dict(row._mapping) if row else None
        except Exception as e:
            logger.log_db_query(str(query), {"action_id": action_id}, error=e)
            return None

    async def cleanup_old_actions(self, days: int = 365) -> int:
        """Delete actions older than N days. Returns count of deleted actions."""
        query = text("""
            DELETE FROM admin_actions
            WHERE created_at < NOW() - INTERVAL '1 day' * :days
        """)

        params = {"days": days}

        try:
            logger.log_db_operation(str(query), params)
            async with get_db_session() as session:
                result = await session.execute(query, params)
                logger.log_db_query(str(query), params, f"DELETE {result.rowcount}")
                await session.commit()
                return result.rowcount
        except Exception as e:
            logger.log_db_query(str(query), params, error=e)
            return 0
