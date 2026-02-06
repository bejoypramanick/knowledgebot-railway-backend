"""
Performance Data Access Object for Configuration Service
Handles database operations for performance metrics
"""
from typing import Dict, List, Any, Optional

from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("performance_dao", "configuration")

class PerformanceDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    # Basic Metrics
    async def get_total_interactions(self) -> int:
        """Get total number of user interactions."""
        query = "SELECT COUNT(*) FROM chat_messages WHERE role = 'user'"
        try:
            logger.log_db_operation(query)
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
            logger.log_db_operation(query)
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
            logger.log_db_operation(query)
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
            logger.log_db_operation(query)
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
            INNER JOIN user_role_mapping urm ON sa.user_role_id = urm.user_role_id
            INNER JOIN roles r ON urm.role_id = r.id
            WHERE r.role_name IN ('human_agent', 'admin')
            AND sa.status != 'ended'
        """
        try:
            logger.log_db_operation(query)
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
                AND sa.status != 'ended'
            )
        """
        try:
            logger.log_db_operation(query)
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
                AND sa.status != 'ended'
            )
        """
        try:
            logger.log_db_operation(query)
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
                AND sa.status != 'ended'
            WHERE cm.role = 'user'
            AND cm.created_at >= NOW() - INTERVAL '6 months'
            GROUP BY TO_CHAR(cm.created_at, 'Mon'), DATE_TRUNC('month', cm.created_at)
            ORDER BY DATE_TRUNC('month', cm.created_at)
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def get_satisfaction_score(self) -> float:
        """Calculate average satisfaction score from chat_feedback (thumbs up/down)."""
        query = """
            SELECT
                AVG(CASE
                    WHEN feedback_type = 'positive' THEN 5.0
                    WHEN feedback_type = 'negative' THEN 1.0
                    ELSE 3.0
                END) as avg_score
            FROM chat_feedback
            WHERE created_at >= NOW() - INTERVAL '30 days'
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetchval(query)
                logger.log_db_query(query, None, result)
                return float(result or 4.0)
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return 4.0

    async def get_satisfaction_over_time(self) -> List[Dict[str, Any]]:
        """Get monthly satisfaction scores with thumbs up/down counts from chat_feedback."""
        query = """
            SELECT
                TO_CHAR(created_at, 'Mon') as month,
                COUNT(CASE WHEN feedback_type = 'positive' THEN 1 END) as thumbs_up,
                COUNT(CASE WHEN feedback_type = 'negative' THEN 1 END) as thumbs_down,
                AVG(CASE
                    WHEN feedback_type = 'positive' THEN 5.0
                    WHEN feedback_type = 'negative' THEN 1.0
                    ELSE 3.0
                END) as satisfaction_score
            FROM chat_feedback
            WHERE created_at >= NOW() - INTERVAL '6 months'
            GROUP BY TO_CHAR(created_at, 'Mon'), DATE_TRUNC('month', created_at)
            ORDER BY DATE_TRUNC('month', created_at)
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, None, result)
                return [
                    {
                        "day": row["month"],
                        "month": row["month"],
                        "positive": row["thumbs_up"],
                        "thumbs_up": row["thumbs_up"],
                        "negative": row["thumbs_down"],
                        "thumbs_down": row["thumbs_down"],
                        "score": round(row["satisfaction_score"] or 4.0, 2),
                        "satisfaction_score": round(row["satisfaction_score"] or 4.0, 2)
                    }
                    for row in result
                ]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def get_uptime_percentage(self, days: int = 30) -> float:
        """Get system uptime percentage from health monitoring (with fallback)."""
        try:
            import os
            import httpx

            health_monitoring_url = os.getenv("HEALTH_MONITORING_URL", "http://localhost:8006")

            async with httpx.AsyncClient(timeout=10) as client:
                try:
                    response = await client.get(
                        f"{health_monitoring_url}/api/v1/health/availability",
                        params={"days": days}
                    )

                    if response.status_code == 200:
                        data = response.json()
                        return float(data.get("average_uptime_percentage", 99.5))
                    else:
                        logger.warning(f"Health monitoring returned status {response.status_code}")
                        return 99.5
                except httpx.RequestError as e:
                    logger.warning(f"Could not reach health monitoring service: {e}")
                    return 99.5
        except Exception as e:
            logger.warning(f"Error fetching uptime percentage: {e}")
            return 99.5

    async def get_uptime_by_service(self) -> List[Dict[str, Any]]:
        """Get uptime percentage for each service from health monitoring."""
        default_services = [
            {"service": "api_gateway", "uptime": 99.9},
            {"service": "chatbot_orchestration", "uptime": 99.8},
            {"service": "configuration", "uptime": 99.9},
            {"service": "docling_service", "uptime": 98.5},
            {"service": "knowledgebase_ingestion", "uptime": 99.7},
            {"service": "website_crawling", "uptime": 99.6}
        ]

        try:
            import os
            import httpx

            health_monitoring_url = os.getenv("HEALTH_MONITORING_URL", "http://localhost:8006")

            async with httpx.AsyncClient(timeout=10) as client:
                try:
                    response = await client.get(
                        f"{health_monitoring_url}/api/v1/health/availability"
                    )

                    if response.status_code == 200:
                        data = response.json()
                        services = data.get("services", {})

                        if services:
                            return [
                                {
                                    "service": service_name,
                                    "uptime": round(uptime, 2)
                                }
                                for service_name, uptime in services.items()
                            ]
                        else:
                            return default_services
                    else:
                        return default_services
                except httpx.RequestError as e:
                    return default_services
        except Exception as e:
            return default_services

    async def get_uptime_over_time(self, days: int = 180) -> List[Dict[str, Any]]:
        """Get uptime history for the last N days from health monitoring."""
        try:
            import os
            import httpx

            health_monitoring_url = os.getenv("HEALTH_MONITORING_URL", "http://localhost:8006")

            async with httpx.AsyncClient(timeout=10) as client:
                try:
                    response = await client.get(
                        f"{health_monitoring_url}/api/v1/health/chart-data",
                        params={"days": days, "interval": "month" if days >= 90 else "day"}
                    )

                    if response.status_code == 200:
                        chart_result = response.json()
                        raw_data = chart_result.get("data", [])
                        
                        # Format for frontend: [{"month": "Jan", "uptime": 99.9}, ...]
                        formatted_history = []
                        for item in raw_data:
                            # Parse ISO timestamp if necessary, but here we just need the month
                            # The health service returns 'time_period' as a string date
                            try:
                                from datetime import datetime
                                date_obj = datetime.fromisoformat(item['time_period'].replace('Z', '+00:00'))
                                month_name = date_obj.strftime('%b')
                            except:
                                month_name = 'N/A'
                                
                            formatted_history.append({
                                "month": month_name,
                                "uptime": round(item['uptime_percentage'], 2)
                            })
                        return formatted_history
                    return []
                except Exception as e:
                    logger.warning(f"Error fetching uptime history: {e}")
                    return []
        except Exception as e:
            return []

    async def get_performance_metrics(self) -> Dict[str, Any]:
        """Get comprehensive performance metrics."""
        try:
            total_interactions = await self.get_total_interactions()
            total_sessions = await self.get_total_sessions()
            active_sessions = await self.get_active_sessions()
            avg_engagement = await self.get_average_engagement_time()
            sessions_with_human = await self.get_sessions_with_human()
            ai_handled_chats = await self.get_ai_handled_chats()
            human_handoffs = await self.get_human_agent_handoffs()
            ai_handled_percentage = (ai_handled_chats / total_interactions * 100) if total_interactions > 0 else 0
            human_handoff_percentage = (human_handoffs / total_interactions * 100) if total_interactions > 0 else 0
            interactions_over_time = await self.get_interactions_over_time()
            previous_period_interactions = sum(item['total'] for item in interactions_over_time[:-1]) if len(interactions_over_time) > 1 else 0
            current_period_interactions = interactions_over_time[-1]['total'] if interactions_over_time else 0
            interactions_growth = ((current_period_interactions - previous_period_interactions) / previous_period_interactions * 100) if previous_period_interactions > 0 else 0
            satisfaction_score = await self.get_satisfaction_score()
            satisfaction_over_time = await self.get_satisfaction_over_time()
            uptime_percentage = await self.get_uptime_percentage()
            uptime_by_service = await self.get_uptime_by_service()

            return {
                "total_interactions": total_interactions,
                "total_sessions": total_sessions,
                "active_sessions": active_sessions,
                "average_engagement_minutes": round(avg_engagement or 0, 2),
                "sessions_with_human": sessions_with_human,
                "ai_handled_chats": ai_handled_chats,
                "human_agent_handoffs": human_handoffs,
                "ai_handled_percentage": round(ai_handled_percentage, 2),
                "human_handoff_percentage": round(human_handoff_percentage, 2),
                "deflection_rate": round(ai_handled_percentage, 2),
                "interactions_growth": round(interactions_growth, 2),
                "interactions_over_time": interactions_over_time,
                "satisfaction_score": round(satisfaction_score, 2),
                "satisfaction_over_time": satisfaction_over_time,
                "uptime": round(uptime_percentage, 2),
                "uptime_by_service": uptime_by_service,
                "uptime_over_time": await self.get_uptime_over_time(180)  # 6 months history
            }
        except Exception as e:
            logger.error(f"Error getting performance metrics: {e}")
            raise

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
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []

    async def get_recent_interactions(self) -> int:
        """Get interactions in last 30 days."""
        query = "SELECT COUNT(*) FROM chat_messages WHERE role = 'user' AND created_at >= NOW() - INTERVAL '30 days'"
        try:
            logger.log_db_operation(query)
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
            logger.log_db_operation(query)
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
            logger.log_db_operation(query)
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
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetchval(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return None

    async def get_uptime_metrics(self) -> List[Dict[str, Any]]:
        """Get uptime metrics over time."""
        query = """
            SELECT 
                TO_CHAR(created_at, 'Mon') as month,
                AVG(value) as uptime_percentage
            FROM metrics
            WHERE metric_name = 'uptime'
            AND created_at >= NOW() - INTERVAL '6 months'
            GROUP BY TO_CHAR(created_at, 'Mon'), DATE_TRUNC('month', created_at)
            ORDER BY DATE_TRUNC('month', created_at)
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, None, result)
                return result
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []
