"""Data Access Object for health monitoring operations."""
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from health_monitoring.core.db import get_db_connection

logger = logging.getLogger(__name__)


class HealthDAO:
    """DAO for health check operations."""

    @staticmethod
    async def insert_health_check(
        service_name: str,
        status: str,
        response_time_ms: Optional[int],
        timestamp: Optional[datetime] = None,
        error_message: Optional[str] = None,
        metadata: Optional[Dict[str, Any]] = None
    ) -> int:
        """Insert a health check record."""
        if timestamp is None:
            timestamp = datetime.utcnow()

        query = """
            INSERT INTO service_health_checks
            (service_name, status, response_time_ms, checked_at, error_message, metadata)
            VALUES ($1, $2, $3, $4, $5, $6)
            RETURNING id
        """

        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(
                    query,
                    service_name,
                    status,
                    response_time_ms,
                    timestamp,
                    error_message,
                    metadata
                )
                logger.info(f"✅ Inserted health check for {service_name}: {status}")
                return result
        except Exception as e:
            logger.error(f"❌ Failed to insert health check for {service_name}: {e}")
            raise

    @staticmethod
    async def get_uptime_by_service(
        service_name: str,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> float:
        """Calculate uptime percentage for a service."""
        if start_date is None:
            start_date = datetime.utcnow() - timedelta(days=30)
        if end_date is None:
            end_date = datetime.utcnow()

        query = """
            SELECT
                COUNT(CASE WHEN status = 'healthy' THEN 1 END) * 100.0 / COUNT(*) as uptime_percentage
            FROM service_health_checks
            WHERE service_name = $1
            AND checked_at >= $2
            AND checked_at <= $3
        """

        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, service_name, start_date, end_date)
                return float(result) if result else 0.0
        except Exception as e:
            logger.error(f"❌ Failed to get uptime for {service_name}: {e}")
            return 0.0

    @staticmethod
    async def get_all_services_uptime(
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> Dict[str, float]:
        """Get uptime percentage for all services."""
        if start_date is None:
            start_date = datetime.utcnow() - timedelta(days=30)
        if end_date is None:
            end_date = datetime.utcnow()

        query = """
            SELECT
                service_name,
                COUNT(CASE WHEN status = 'healthy' THEN 1 END) * 100.0 / COUNT(*) as uptime_percentage
            FROM service_health_checks
            WHERE checked_at >= $1
            AND checked_at <= $2
            GROUP BY service_name
        """

        try:
            async with get_db_connection() as conn:
                results = await conn.fetch(query, start_date, end_date)
                return {row['service_name']: float(row['uptime_percentage']) for row in results}
        except Exception as e:
            logger.error(f"❌ Failed to get uptime for all services: {e}")
            return {}

    @staticmethod
    async def get_recent_failures(limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent service failures."""
        query = """
            SELECT
                service_name,
                status,
                response_time_ms,
                checked_at,
                error_message
            FROM service_health_checks
            WHERE status != 'healthy'
            ORDER BY checked_at DESC
            LIMIT $1
        """

        try:
            async with get_db_connection() as conn:
                results = await conn.fetch(query, limit)
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"❌ Failed to get recent failures: {e}")
            return []

    @staticmethod
    async def get_uptime_over_time(
        service_name: Optional[str] = None,
        interval: str = 'day'
    ) -> List[Dict[str, Any]]:
        """Get uptime data over time for charting."""
        if interval not in ['hour', 'day', 'week', 'month']:
            interval = 'day'

        interval_map = {
            'hour': "DATE_TRUNC('hour', checked_at)",
            'day': "DATE_TRUNC('day', checked_at)",
            'week': "DATE_TRUNC('week', checked_at)",
            'month': "DATE_TRUNC('month', checked_at)"
        }

        time_bucket = interval_map[interval]

        if service_name:
            query = f"""
                SELECT
                    {time_bucket} as time_period,
                    COUNT(CASE WHEN status = 'healthy' THEN 1 END) * 100.0 / COUNT(*) as uptime_percentage
                FROM service_health_checks
                WHERE service_name = $1
                AND checked_at >= NOW() - INTERVAL '90 days'
                GROUP BY {time_bucket}
                ORDER BY {time_bucket}
            """
            try:
                async with get_db_connection() as conn:
                    results = await conn.fetch(query, service_name)
                    return [dict(row) for row in results]
            except Exception as e:
                logger.error(f"❌ Failed to get uptime over time for {service_name}: {e}")
                return []
        else:
            query = f"""
                SELECT
                    {time_bucket} as time_period,
                    service_name,
                    COUNT(CASE WHEN status = 'healthy' THEN 1 END) * 100.0 / COUNT(*) as uptime_percentage
                FROM service_health_checks
                WHERE checked_at >= NOW() - INTERVAL '90 days'
                GROUP BY {time_bucket}, service_name
                ORDER BY {time_bucket}, service_name
            """
            try:
                async with get_db_connection() as conn:
                    results = await conn.fetch(query)
                    return [dict(row) for row in results]
            except Exception as e:
                logger.error(f"❌ Failed to get uptime over time for all services: {e}")
                return []

    @staticmethod
    async def get_latest_check(service_name: str) -> Optional[Dict[str, Any]]:
        """Get the latest health check for a service."""
        query = """
            SELECT
                service_name,
                status,
                response_time_ms,
                checked_at,
                error_message,
                metadata
            FROM service_health_checks
            WHERE service_name = $1
            ORDER BY checked_at DESC
            LIMIT 1
        """

        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, service_name)
                return dict(result) if result else None
        except Exception as e:
            logger.error(f"❌ Failed to get latest check for {service_name}: {e}")
            return None

    @staticmethod
    async def get_all_latest_checks() -> List[Dict[str, Any]]:
        """Get the latest health check for all services."""
        query = """
            SELECT
                service_name,
                status,
                response_time_ms,
                checked_at,
                error_message,
                metadata
            FROM (
                SELECT
                    *,
                    ROW_NUMBER() OVER (PARTITION BY service_name ORDER BY checked_at DESC) as rn
                FROM service_health_checks
            ) AS subquery
            WHERE rn = 1
            ORDER BY service_name
        """

        try:
            async with get_db_connection() as conn:
                results = await conn.fetch(query)
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"❌ Failed to get all latest checks: {e}")
            return []
