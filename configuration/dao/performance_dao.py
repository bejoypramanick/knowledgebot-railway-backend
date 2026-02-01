f"""
Performance Data Access Object for Configuration Service
Handles database operations for performance metrics
"""
from typing import Dict, List, Any, Optional

from configuration.core.db import get_db_connection
from configuration.core.otel_logger import get_otel_logger

logger = get_otel_logger("performance_dao", "configuration")

class PerformanceDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    # Basic Metrics
    async def get_total_interactions(self) -> int:
        """Get total number of user interactions."""
        query = "SELECT COUNT(*) FROM chat_messages WHERE role = 'user'"
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return 0

    async def get_total_sessions(self) -> int:
        """Get total number of chat sessions."""
        query = "SELECT COUNT(*) FROM chat_sessions"
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return 0

    async def get_active_sessions(self) -> int:
        """Get number of active sessions (last 24 hours)."""
        query = """
            SELECT COUNT(*) FROM chat_sessions
            WHERE last_activity_at >= NOW() - INTERVAL '24 hours'
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return 0

    async def get_average_engagement_time(self) -> Optional[float]:
        """Get average engagement time in minutes."""
        query = """
            SELECT AVG(EXTRACT(EPOCH FROM (last_activity_at - created_at)) / 60)
            FROM chat_sessions
            WHERE last_activity_at IS NOT NULL AND created_at IS NOT NULL
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return None

    async def get_sessions_with_human(self) -> int:
        """Get number of sessions that had human agent involvement."""
        query = """
            SELECT COUNT(DISTINCT cs.id)
            FROM chat_sessions cs
            INNER JOIN session_assignments sa ON cs.id = sa.session_id
            WHERE sa.assignee_type IN ('agent', 'admin')
            AND sa.status != 'ended'
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return 0

    # AI vs Human Metrics
    async def get_ai_handled_chats(self) -> int:
        """Get number of chats handled by AI."""
        query = """
            SELECT COUNT(*)
            FROM chat_messages cm
            WHERE cm.role = 'user'
            AND NOT EXISTS (
                SELECT 1 FROM session_assignments sa
                WHERE sa.session_id = cm.session_id
                AND sa.assignee_type IN ('agent', 'admin')
                AND sa.status != 'ended'
            )
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return 0

    async def get_human_agent_handoffs(self) -> int:
        """Get number of chats handed off to human agents."""
        query = """
            SELECT COUNT(*)
            FROM chat_messages cm
            WHERE cm.role = 'user'
            AND EXISTS (
                SELECT 1 FROM session_assignments sa
                WHERE sa.session_id = cm.session_id
                AND sa.assignee_type IN ('agent', 'admin')
                AND sa.status != 'ended'
            )
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return 0

    async def get_interactions_over_time(self) -> List[Dict[str, Any]]:
        """Get interactions breakdown over time (last 6 months)."""
        query = """
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
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def get_performance_metrics(self) -> Dict[str, Any]:
        """Get comprehensive performance metrics."""
        try:
            # Get basic metrics
            total_interactions = await self.get_total_interactions()
            total_sessions = await self.get_total_sessions()
            active_sessions = await self.get_active_sessions()
            avg_engagement = await self.get_average_engagement_time()
            sessions_with_human = await self.get_sessions_with_human()
            
            # Get AI vs Human metrics
            ai_handled_chats = await self.get_ai_handled_chats()
            human_handoffs = await self.get_human_agent_handoffs()
            
            # Calculate percentages
            ai_handled_percentage = (ai_handled_chats / total_interactions * 100) if total_interactions > 0 else 0
            human_handoff_percentage = (human_handoffs / total_interactions * 100) if total_interactions > 0 else 0
            
            # Get interactions over time
            interactions_over_time = await self.get_interactions_over_time()
            
            # Calculate growth (compare with previous period)
            previous_period_interactions = sum(item['total'] for item in interactions_over_time[:-1]) if len(interactions_over_time) > 1 else 0
            current_period_interactions = interactions_over_time[-1]['total'] if interactions_over_time else 0
            interactions_growth = ((current_period_interactions - previous_period_interactions) / previous_period_interactions * 100) if previous_period_interactions > 0 else 0
            
            return {
                "total_interactions": total_interactions,
                "total_sessions": total_sessions,
                "active_sessions": active_sessions,
                "average_engagement_minutes": round(avg_engagement or 0, 2),
                "sessions_with_human": sessions_with_human,
                "ai_handled_chats": ai_handled_chats,
                "human_handoffs": human_handoffs,
                "ai_handled_percentage": round(ai_handled_percentage, 2),
                "human_handoff_percentage": round(human_handoff_percentage, 2),
                "interactions_growth": round(interactions_growth, 2),
                "interactions_over_time": interactions_over_time,
                "user_satisfaction": 4.5  # Placeholder - would need feedback data
            }
        except Exception as e:
            logger.error(f"Error getting performance metrics: {e}")
            raise

    # Satisfaction Metrics
    async def get_satisfaction_metrics(self) -> List[Dict[str, Any]]:
        """Get satisfaction metrics over time."""
        query = """
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
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    # Comparison Metrics
    async def get_recent_interactions(self) -> int:
        """Get interactions in last 30 days."""
        query = "SELECT COUNT(*) FROM chat_messages WHERE role = 'user' AND created_at >= NOW() - INTERVAL '30 days'"
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query)
                logger.log_db_query(query, None, result)
                return result or 0
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return 0

    async def get_previous_interactions(self) -> int:
        """Get interactions from 30-60 days ago."""
        query = "SELECT COUNT(*) FROM chat_messages WHERE role = 'user' AND created_at >= NOW() - INTERVAL '60 days' AND created_at < NOW() - INTERVAL '30 days'"
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query)
                logger.log_db_query(query, None, result)
                return result or 0
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return 0

    async def get_recent_engagement(self) -> Optional[float]:
        """Get average engagement time for last 30 days."""
        query = """
            SELECT AVG(EXTRACT(EPOCH FROM (last_activity_at - created_at)) / 60)
            FROM chat_sessions
            WHERE last_activity_at >= NOW() - INTERVAL '30 days'
            AND last_activity_at IS NOT NULL AND created_at IS NOT NULL
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return None

    async def get_previous_engagement(self) -> Optional[float]:
        """Get average engagement time from 30-60 days ago."""
        query = """
            SELECT AVG(EXTRACT(EPOCH FROM (last_activity_at - created_at)) / 60)
            FROM chat_sessions
            WHERE last_activity_at >= NOW() - INTERVAL '60 days'
            AND last_activity_at < NOW() - INTERVAL '30 days'
            AND last_activity_at IS NOT NULL AND created_at IS NOT NULL
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return None

    # Uptime Metrics
    async def get_uptime_metrics(self) -> List[Dict[str, Any]]:
        """Get uptime metrics over time."""
        query = """
            SELECT 
                TO_CHAR(recorded_at, 'Mon') as month,
                AVG(value) as uptime_percentage
            FROM metrics
            WHERE metric_name = 'uptime'
            AND recorded_at >= NOW() - INTERVAL '6 months'
            GROUP BY TO_CHAR(recorded_at, 'Mon'), DATE_TRUNC('month', recorded_at)
            ORDER BY DATE_TRUNC('month', recorded_at)
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []
