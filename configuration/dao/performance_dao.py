"""
Performance Data Access Object for Configuration Service
Handles database operations for performance metrics
"""
from typing import Dict, List, Any, Optional

from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("performance_dao", "configuration")


def format_service_name(service_name: str) -> str:
    """Convert snake_case service name to human-readable format.

    Examples:
        api_gateway → API Gateway
        chatbot_orchestration → Chatbot Orchestration
        knowledgebase_ingestion → Knowledgebase Ingestion
        website_crawling → Website Crawling
        docling_service → Docling Service
        configuration → Configuration
    """
    # Mapping of service names to display names
    service_display_names = {
        'api_gateway': 'API Gateway',
        'chatbot_orchestration': 'Chatbot Orchestration',
        'knowledgebase_ingestion': 'Knowledgebase Ingestion',
        'website_crawling': 'Website Crawling',
        'docling_service': 'Docling Service',
        'configuration': 'Configuration',
    }

    # Return mapped name if exists, otherwise convert snake_case to title case
    if service_name in service_display_names:
        return service_display_names[service_name]

    # Fallback: convert snake_case to title case
    return ' '.join(word.capitalize() for word in service_name.split('_'))


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

    # AI vs Human Metrics - Now session-based for accuracy
    async def get_ai_handled_chats(self) -> int:
        """Get number of sessions handled purely by AI (no human assignment)."""
        query = """
            SELECT COUNT(*)
            FROM chat_sessions cs
            WHERE NOT EXISTS (
                SELECT 1 FROM session_assignments sa
                WHERE sa.session_id = cs.id
            )
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetchval(query)
                return result or 0
        except Exception as e:
            logger.error(f"Error getting AI handled chats: {e}")
            return 0

    async def get_human_agent_handoffs(self) -> int:
        """Get number of sessions that were assigned to a human agent."""
        query = """
            SELECT COUNT(DISTINCT session_id)
            FROM session_assignments
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetchval(query)
                return result or 0
        except Exception as e:
            logger.error(f"Error getting human handoffs: {e}")
            return 0

    async def get_deflection_rate(self) -> float:
        """Calculate deflection rate as (AI Handled Sessions / Total Sessions) * 100."""
        try:
            total_sessions = await self.get_total_sessions()
            if total_sessions == 0:
                return 0.0
            
            ai_handled = await self.get_ai_handled_chats()
            return (ai_handled / total_sessions) * 100.0
        except Exception as e:
            logger.error(f"Error calculating deflection rate: {e}")
            return 0.0

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

            health_monitoring_url = os.getenv(
                "HEALTH_MONITORING_URL",
                "http://health-monitoring.railway.internal:8080"
            )

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
        """Get uptime percentage for each service from health monitoring with human-readable names."""
        default_services = [
            {"service": format_service_name("api_gateway"), "uptime": 99.9},
            {"service": format_service_name("chatbot_orchestration"), "uptime": 99.8},
            {"service": format_service_name("configuration"), "uptime": 99.9},
            {"service": format_service_name("docling_service"), "uptime": 98.5},
            {"service": format_service_name("knowledgebase_ingestion"), "uptime": 99.7},
            {"service": format_service_name("website_crawling"), "uptime": 99.6}
        ]

        try:
            import os
            import httpx

            health_monitoring_url = os.getenv(
                "HEALTH_MONITORING_URL",
                "http://health-monitoring.railway.internal:8080"
            )

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
                                    "service": format_service_name(service_name),
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
        """Get uptime history for the last N days (6 months) with service-wise breakdown.

        Returns all 6 months with uptime data for each service, including healthcheck count
        and average frequency. Months without health check records show uptime as 0.
        This provides a consistent 6-month view with service-level granularity.
        """
        try:
            from datetime import datetime, timedelta
            import calendar

            logger.info(f"📊 Calculating uptime history from service_health_checks table for last {days} days")

            # Query to get uptime data by service and month
            query = """
            WITH monthly_health AS (
                SELECT
                    DATE_TRUNC('month', checked_at AT TIME ZONE 'UTC') as month,
                    service_name,
                    COUNT(*) as total_checks,
                    COUNT(CASE WHEN status = 'healthy' THEN 1 END) as healthy_checks
                FROM service_health_checks
                WHERE checked_at >= NOW() - INTERVAL '%s days'
                GROUP BY DATE_TRUNC('month', checked_at AT TIME ZONE 'UTC'), service_name
            )
            SELECT
                month,
                service_name,
                ROUND((healthy_checks::float / NULLIF(total_checks, 0) * 100)::numeric, 2) as uptime_percentage,
                total_checks,
                healthy_checks
            FROM monthly_health
            ORDER BY month DESC, service_name
            """

            async with get_db_connection() as conn:
                results = await conn.fetch(query % days)
                logger.info(f"📊 Retrieved {len(results)} uptime records from database")

            # Organize data by month and service, including healthcheck metadata
            month_data_map = {}
            for row in results:
                month = row['month']
                service = row['service_name']
                uptime = float(row['uptime_percentage']) if row['uptime_percentage'] else 0
                healthcheck_count = row['total_checks']

                if month not in month_data_map:
                    month_data_map[month] = {}

                # Format service name
                formatted_service = format_service_name(service)

                # Calculate days in month for frequency calculation
                month_date = month
                days_in_month = calendar.monthrange(month_date.year, month_date.month)[1]
                healthcheck_frequency = round(healthcheck_count / days_in_month, 2)  # checks per day

                month_data_map[month][formatted_service] = {
                    "uptime": round(uptime, 2),
                    "healthcheck_count": healthcheck_count,
                    "healthcheck_frequency": healthcheck_frequency
                }

            # Generate all 6 months (current month + 5 previous months)
            now = datetime.utcnow()
            formatted_history = []

            # Generate 6 months backwards from current month
            current_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
            for i in range(5, -1, -1):  # 5, 4, 3, 2, 1, 0 (6 months back from current)
                # Calculate month date by going back i months
                month_date = current_month
                for _ in range(i):
                    # Go to previous month
                    if month_date.month == 1:
                        month_date = month_date.replace(year=month_date.year - 1, month=12)
                    else:
                        month_date = month_date.replace(month=month_date.month - 1)

                month_label = month_date.strftime('%b %Y')

                # Get service data for this month if available
                services_for_month = month_data_map.get(month_date, {})

                # If no data for this month, create entries for all known services with 0 uptime
                if not services_for_month:
                    all_services = ['API Gateway', 'Chatbot Orchestration', 'Configuration',
                                   'Docling Service', 'Knowledgebase Ingestion', 'Website Crawling']
                    services_for_month = {
                        service: {
                            "uptime": 0,
                            "healthcheck_count": 0,
                            "healthcheck_frequency": 0
                        }
                        for service in all_services
                    }

                formatted_history.append({
                    "month": month_label,
                    "services": [
                        {
                            "service": service,
                            "uptime": data["uptime"],
                            "healthcheck_count": data["healthcheck_count"],
                            "healthcheck_frequency": data["healthcheck_frequency"]
                        }
                        for service, data in sorted(services_for_month.items())
                    ]
                })

            logger.info(f"✅ Formatted 6 months of uptime history with service breakdown and healthcheck metadata")
            return formatted_history

        except Exception as e:
            logger.error(f"❌ Error in get_uptime_over_time: {e}", exc_info=True)
            # Return 6 empty months with all services on error
            try:
                from datetime import datetime
                now = datetime.utcnow()
                current_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                empty_months = []
                all_services = ['API Gateway', 'Chatbot Orchestration', 'Configuration',
                               'Docling Service', 'Knowledgebase Ingestion', 'Website Crawling']

                for i in range(5, -1, -1):
                    month_date = current_month
                    for _ in range(i):
                        if month_date.month == 1:
                            month_date = month_date.replace(year=month_date.year - 1, month=12)
                        else:
                            month_date = month_date.replace(month=month_date.month - 1)

                    empty_months.append({
                        "month": month_date.strftime('%b %Y'),
                        "services": [
                            {
                                "service": s,
                                "uptime": 0,
                                "healthcheck_count": 0,
                                "healthcheck_frequency": 0
                            }
                            for s in all_services
                        ]
                    })
                return empty_months
            except Exception as inner_e:
                logger.error(f"❌ Error generating fallback empty months: {inner_e}")
                return []

    async def get_performance_metrics(self) -> Dict[str, Any]:
        try:
            total_interactions = await self.get_total_interactions() or 0
            total_sessions = await self.get_total_sessions() or 0
            active_sessions = await self.get_active_sessions() or 0
            avg_engagement = await self.get_average_engagement_time() or 0
            sessions_with_human = await self.get_sessions_with_human() or 0

            ai_handled_chats = await self.get_ai_handled_chats() or 0
            human_handoffs = await self.get_human_agent_handoffs() or 0

            # Use sessions for percentages if possible, otherwise interactions
            total_for_calc = total_sessions if total_sessions > 0 else total_interactions
            ai_handled_percentage = (ai_handled_chats / total_for_calc * 100) if total_for_calc > 0 else 0
            human_handoff_percentage = (human_handoffs / total_for_calc * 100) if total_for_calc > 0 else 0

            # Use specialized deflection rate method
            deflection_rate = await self.get_deflection_rate()

            interactions_over_time = await self.get_interactions_over_time()

            # Calculate growth based on last two time periods
            interactions_growth = 0
            if len(interactions_over_time) >= 2:
                prev = interactions_over_time[-2].get('total', 0)
                curr = interactions_over_time[-1].get('total', 0)
                if prev > 0:
                    interactions_growth = ((curr - prev) / prev) * 100
                elif curr > 0:
                    interactions_growth = 100

            satisfaction_score = await self.get_satisfaction_score()
            satisfaction_over_time = await self.get_satisfaction_over_time()

            uptime_percentage = await self.get_uptime_percentage()
            uptime_by_service = await self.get_uptime_by_service()
            uptime_history = await self.get_uptime_over_time(180)

            # Extract available services from uptime_by_service
            available_services = [service["service"] for service in uptime_by_service]

            return {
                "total_interactions": total_interactions,
                "total_sessions": total_sessions,
                "active_sessions": active_sessions,
                "average_engagement_minutes": round(avg_engagement, 2),
                "sessions_with_human": sessions_with_human,
                "ai_handled_chats": ai_handled_chats,
                "human_agent_handoffs": human_handoffs,
                "ai_handled_percentage": round(ai_handled_percentage, 2),
                "human_handoff_percentage": round(human_handoff_percentage, 2),
                "deflection_rate": round(deflection_rate, 2),
                "interactions_growth": round(interactions_growth, 2),
                "interactions_over_time": interactions_over_time,
                "satisfaction_score": round(satisfaction_score, 2),
                "satisfaction_over_time": satisfaction_over_time,
                "uptime": round(uptime_percentage, 2),
                "uptime_by_service": uptime_by_service,
                "uptime_over_time": uptime_history,
                "average_uptime_percentage": round(uptime_percentage, 2),
                "available_services": available_services
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
