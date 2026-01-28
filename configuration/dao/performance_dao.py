from shared.logging_config import get_railway_logger
import logging
from typing import Optional, Dict, Any, List, Tuple
from datetime import datetime, timedelta
from shared.db import get_db_connection

logger = get_railway_logger(__name__)

class PerformanceDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    # Basic Metrics
    async def get_total_interactions(self) -> int:
        """Get total number of user interactions."""
        async with get_db_connection() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM chat_messages WHERE role = 'user'")

    async def get_total_sessions(self) -> int:
        """Get total number of chat sessions."""
        async with get_db_connection() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM chat_sessions")

    async def get_active_sessions(self) -> int:
        """Get number of active sessions (last 24 hours)."""
        async with get_db_connection() as conn:
            return await conn.fetchval("""
                SELECT COUNT(*) FROM chat_sessions
                WHERE last_activity_at >= NOW() - INTERVAL '24 hours'
            """)

    async def get_average_engagement_time(self) -> Optional[float]:
        """Get average engagement time in minutes."""
        async with get_db_connection() as conn:
            return await conn.fetchval("""
                SELECT AVG(EXTRACT(EPOCH FROM (last_activity_at - created_at)) / 60)
                FROM chat_sessions
                WHERE last_activity_at IS NOT NULL AND created_at IS NOT NULL
            """)

    async def get_sessions_with_human(self) -> int:
        """Get number of sessions that had human agent involvement."""
        async with get_db_connection() as conn:
            return await conn.fetchval("""
                SELECT COUNT(DISTINCT cs.id)
                FROM chat_sessions cs
                INNER JOIN session_assignments sa ON cs.id = sa.session_id
                WHERE sa.assignee_type IN ('agent', 'admin')
                AND sa.status != 'ended'
            """)

    # AI vs Human Metrics
    async def get_ai_handled_chats(self) -> int:
        """Get number of chats handled by AI."""
        async with get_db_connection() as conn:
            return await conn.fetchval("""
                SELECT COUNT(*)
                FROM chat_messages cm
                WHERE cm.role = 'user'
                AND NOT EXISTS (
                    SELECT 1 FROM session_assignments sa
                    WHERE sa.session_id = cm.session_id
                    AND sa.assignee_type IN ('agent', 'admin')
                    AND sa.status != 'ended'
                )
            """)

    async def get_human_agent_handoffs(self) -> int:
        """Get number of chats handed off to human agents."""
        async with get_db_connection() as conn:
            return await conn.fetchval("""
                SELECT COUNT(*)
                FROM chat_messages cm
                WHERE cm.role = 'user'
                AND EXISTS (
                    SELECT 1 FROM session_assignments sa
                    WHERE sa.session_id = cm.session_id
                    AND sa.assignee_type IN ('agent', 'admin')
                    AND sa.status != 'ended'
                )
            """)

    async def get_interactions_over_time(self) -> List[Dict[str, Any]]:
        """Get interactions breakdown over time (last 6 months)."""
        async with get_db_connection() as conn:
            return await conn.fetch("""
                SELECT
                    TO_CHAR(cm.created_at, 'Mon') as month,
                    COUNT(*) as total,
                    COUNT(*) FILTER (WHERE sa.session_id IS NULL) as ai_handled,
                    COUNT(*) FILTER (WHERE sa.session_id IS NOT NULL) as human_handoff
                FROM chat_messages cm
                LEFT JOIN session_assignments sa ON cm.session_id = sa.session_id
                    AND sa.assignee_type IN ('agent', 'admin')
                AND sa.status != 'ended'
            WHERE cm.role = 'user'
            AND cm.created_at >= NOW() - INTERVAL '6 months'
            GROUP BY TO_CHAR(cm.created_at, 'Mon'), DATE_TRUNC('month', cm.created_at)
            ORDER BY DATE_TRUNC('month', cm.created_at)
        """)

    # Satisfaction Metrics
    async def get_satisfaction_metrics(self) -> List[Dict[str, Any]]:
        """Get satisfaction metrics over time."""
        async with get_db_connection() as conn:
            return await conn.fetch("""
                WITH monthly_feedback AS (
                    SELECT
                        DATE_TRUNC('month', created_at) as month_date,
                        AVG(CASE WHEN rating IN (1,2,3,4,5) THEN rating END) as avg_rating,
                        COUNT(CASE WHEN rating IN (1,2,3,4,5) THEN 1 END) as feedback_count
                    FROM chat_messages
                    WHERE role = 'user'
                    AND created_at >= NOW() - INTERVAL '6 months'
                    AND rating IS NOT NULL
                    GROUP BY DATE_TRUNC('month', created_at)
                )
                SELECT
                    TO_CHAR(month_date, 'Mon') as month,
                    COALESCE(avg_rating, 0.0) as satisfaction_score,
                    COALESCE(feedback_count, 0) as total_feedback
                FROM monthly_feedback
                ORDER BY month_date
            """)

    # Comparison Metrics
    async def get_recent_interactions(self) -> int:
        """Get interactions in last 30 days."""
        async with get_db_connection() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM chat_messages WHERE role = 'user' AND created_at >= NOW() - INTERVAL '30 days'") or 0

    async def get_previous_interactions(self) -> int:
        """Get interactions from 30-60 days ago."""
        async with get_db_connection() as conn:
            return await conn.fetchval("SELECT COUNT(*) FROM chat_messages WHERE role = 'user' AND created_at >= NOW() - INTERVAL '60 days' AND created_at < NOW() - INTERVAL '30 days'") or 0

    async def get_recent_engagement(self) -> Optional[float]:
        """Get average engagement time for last 30 days."""
        async with get_db_connection() as conn:
            return await conn.fetchval("""
                SELECT AVG(EXTRACT(EPOCH FROM (last_activity_at - created_at)) / 60)
                FROM chat_sessions
                WHERE last_activity_at >= NOW() - INTERVAL '30 days'
                AND last_activity_at IS NOT NULL AND created_at IS NOT NULL
            """)

    async def get_previous_engagement(self) -> Optional[float]:
        """Get average engagement time from 30-60 days ago."""
        async with get_db_connection() as conn:
            return await conn.fetchval("""
                SELECT AVG(EXTRACT(EPOCH FROM (last_activity_at - created_at)) / 60)
                FROM chat_sessions
                WHERE last_activity_at >= NOW() - INTERVAL '60 days'
                AND last_activity_at < NOW() - INTERVAL '30 days'
                AND last_activity_at IS NOT NULL AND created_at IS NOT NULL
            """)

    # Uptime Metrics
    async def get_uptime_metrics(self) -> List[Dict[str, Any]]:
        """Get uptime metrics over time."""
        async with get_db_connection() as conn:
            return await conn.fetch("""
                SELECT 
                    TO_CHAR(recorded_at, 'Mon') as month,
                    AVG(value) as uptime_percentage
                FROM metrics
                WHERE metric_name = 'uptime'
                AND recorded_at >= NOW() - INTERVAL '6 months'
                GROUP BY TO_CHAR(recorded_at, 'Mon'), DATE_TRUNC('month', recorded_at)
                ORDER BY DATE_TRUNC('month', recorded_at)
            """)

    # Admin and Human Agent Checks
    async def check_admin_exists(self, email: str) -> Optional[Dict[str, Any]]:
        """Check if admin exists for given email."""
        async with get_db_connection() as conn:
            return await conn.fetchrow(
                "SELECT email FROM admins WHERE email = $1",
                email
            )

    async def check_human_agent_exists(self, email: str) -> Optional[Dict[str, Any]]:
        """Check if human agent exists for given email."""
        async with get_db_connection() as conn:
            return await conn.fetchrow(
                "SELECT email FROM human_agents WHERE email = $1",
                email
            )
