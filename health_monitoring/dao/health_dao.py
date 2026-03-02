"""Data Access Object for health monitoring operations."""
import json
import logging
from datetime import datetime, timedelta
from typing import List, Dict, Any, Optional

from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("health_dao", "health_monitoring")


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

        # Convert metadata dict to JSON string for SQLAlchemy JSONB handling
        metadata_json = json.dumps(metadata) if metadata else None

        query = text("""
            INSERT INTO service_health_checks
            (service_name, status, response_time_ms, checked_at, error_message, metadata)
            VALUES (:service_name, :status, :response_time_ms, :checked_at, :error_message, :metadata)
            RETURNING id
        """)

        params = {
            'service_name': service_name,
            'status': status,
            'response_time_ms': response_time_ms,
            'checked_at': timestamp,
            'error_message': error_message,
            'metadata': metadata_json
        }

        try:
            logger.log_db_operation(str(query), params)
            async with get_db_session() as session:
                result = await session.execute(query, params)
                record_id = result.scalar()
                logger.log_db_query(str(query), params, record_id)
                await session.commit()
                return record_id
        except Exception as e:
            logger.log_db_query(str(query), params, error=e)
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

        query = text("""
            SELECT
                COUNT(CASE WHEN status = 'healthy' THEN 1 END) * 100.0 / COUNT(*) as uptime_percentage
            FROM service_health_checks
            WHERE service_name = :service_name
            AND checked_at >= :start_date
            AND checked_at <= :end_date
        """)

        try:
            params = {"service_name": service_name, "start_date": start_date, "end_date": end_date}
            logger.log_db_operation(str(query), params)
            async with get_db_session() as session:
                result = await session.execute(query, params)
                uptime = result.scalar()
                logger.log_db_query(str(query), params, uptime)
                return float(uptime) if uptime else 0.0
        except Exception as e:
            logger.log_db_query(str(query), params, error=e)
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

        query = text("""
            SELECT
                service_name,
                COUNT(CASE WHEN status = 'healthy' THEN 1 END) * 100.0 / COUNT(*) as uptime_percentage
            FROM service_health_checks
            WHERE checked_at >= :start_date
            AND checked_at <= :end_date
            GROUP BY service_name
        """)

        try:
            params = {"start_date": start_date, "end_date": end_date}
            logger.log_db_operation(str(query), params)
            async with get_db_session() as session:
                results = await session.execute(query, params)
                rows = results.fetchall()
                logger.log_db_query(str(query), params, rows)
                return {row.service_name: float(row.uptime_percentage) for row in rows}
        except Exception as e:
            logger.log_db_query(str(query), params, error=e)
            return {}

    @staticmethod
    async def get_recent_failures(limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent service failures."""
        query = text("""
            SELECT
                service_name,
                status,
                response_time_ms,
                checked_at,
                error_message
            FROM service_health_checks
            WHERE status != 'healthy'
            ORDER BY checked_at DESC
            LIMIT :limit
        """)

        try:
            params = {"limit": limit}
            logger.log_db_operation(str(query), params)
            async with get_db_session() as session:
                results = await session.execute(query, params)
                rows = results.fetchall()
                logger.log_db_query(str(query), params, rows)
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.log_db_query(str(query), {"limit": limit}, error=e)
            return []

    @staticmethod
    async def get_uptime_over_time(
        service_name: Optional[str] = None,
        interval: str = 'day',
        days: int = 180  # Default to 6 months
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
            query = text(f"""
                SELECT
                    {time_bucket} as time_period,
                    COUNT(CASE WHEN status = 'healthy' THEN 1 END) * 100.0 / COUNT(*) as uptime_percentage
                FROM service_health_checks
                WHERE service_name = :service_name
                AND checked_at >= NOW() - (:days * INTERVAL '1 day')
                GROUP BY {time_bucket}
                ORDER BY {time_bucket}
            """)
            try:
                params = {"service_name": service_name, "days": days}
                logger.log_db_operation(str(query), params)
                async with get_db_session() as session:
                    results = await session.execute(query, params)
                    rows = results.fetchall()
                    logger.log_db_query(str(query), params, rows)
                    return [dict(row._mapping) for row in rows]
            except Exception as e:
                logger.log_db_query(str(query), {"service_name": service_name, "days": days}, error=e)
                return []
        else:
            query = text(f"""
                SELECT
                    {time_bucket} as time_period,
                    COUNT(CASE WHEN status = 'healthy' THEN 1 END) * 100.0 / COUNT(*) as uptime_percentage
                FROM service_health_checks
                WHERE checked_at >= NOW() - (:days * INTERVAL '1 day')
                GROUP BY {time_bucket}
                ORDER BY {time_bucket}
            """)
            try:
                params = {"days": days}
                logger.log_db_operation(str(query), params)
                async with get_db_session() as session:
                    results = await session.execute(query, params)
                    rows = results.fetchall()
                    logger.log_db_query(str(query), params, rows)
                    return [dict(row._mapping) for row in rows]
            except Exception as e:
                logger.log_db_query(str(query), {"days": days}, error=e)
                return []

    @staticmethod
    async def get_latest_check(service_name: str) -> Optional[Dict[str, Any]]:
        """Get the latest health check for a service."""
        query = text("""
            SELECT
                service_name,
                status,
                response_time_ms,
                checked_at,
                error_message,
                metadata
            FROM service_health_checks
            WHERE service_name = :service_name
            ORDER BY checked_at DESC
            LIMIT 1
        """)

        try:
            params = {"service_name": service_name}
            logger.log_db_operation(str(query), params)
            async with get_db_session() as session:
                result = await session.execute(query, params)
                row = result.fetchone()
                logger.log_db_query(str(query), params, row)
                return dict(row._mapping) if row else None
        except Exception as e:
            logger.log_db_query(str(query), {"service_name": service_name}, error=e)
            return None

    @staticmethod
    async def get_all_latest_checks() -> List[Dict[str, Any]]:
        """Get the latest health check for all services."""
        query = text("""
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
        """)

        try:
            logger.log_db_operation(str(query))
            async with get_db_session() as session:
                results = await session.execute(query)
                rows = results.fetchall()
                logger.log_db_query(str(query), None, rows)
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.log_db_query(str(query), None, error=e)
            return []
