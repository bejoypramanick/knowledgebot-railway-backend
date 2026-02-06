"""Health Monitoring Service for checking all microservices."""
import asyncio
import logging
import time
from typing import Dict, Any, Tuple
from datetime import datetime

import httpx

from health_monitoring.core.config import settings
from health_monitoring.dao.health_dao import HealthDAO

logger = logging.getLogger(__name__)


class HealthMonitoringService:
    """Service to monitor health of all microservices."""

    SERVICES = {
        'api_gateway': {
            'url': settings.api_gateway_url,
            'endpoint': settings.api_gateway_health_endpoint,
        },
        'configuration': {
            'url': settings.configuration_service_url,
            'endpoint': settings.configuration_health_endpoint,
        },
        'chatbot_orchestration': {
            'url': settings.chatbot_orchestration_url,
            'endpoint': settings.chatbot_health_endpoint,
        },
        'knowledgebase_ingestion': {
            'url': settings.knowledgebase_ingestion_url,
            'endpoint': settings.knowledgebase_health_endpoint,
        },
        'website_crawling': {
            'url': settings.website_crawling_url,
            'endpoint': settings.website_crawling_health_endpoint,
        },
        'docling_service': {
            'url': settings.docling_service_url,
            'endpoint': settings.docling_health_endpoint,
        },
    }

    @staticmethod
    async def check_service(
        service_name: str,
        service_config: Dict[str, str]
    ) -> Tuple[str, int, str]:
        """
        Check the health of a single service.

        Returns: (status, response_time_ms, error_message)
        """
        url = f"{service_config['url']}{service_config['endpoint']}"
        start_time = time.time()

        try:
            async with httpx.AsyncClient(timeout=settings.health_check_timeout_seconds) as client:
                response = await client.get(url)
                response_time_ms = int((time.time() - start_time) * 1000)

                if response.status_code == 200:
                    return 'healthy', response_time_ms, None
                else:
                    error_msg = f"HTTP {response.status_code}"
                    return 'degraded', response_time_ms, error_msg
        except asyncio.TimeoutError:
            response_time_ms = int((time.time() - start_time) * 1000)
            error_msg = f"Request timeout after {settings.health_check_timeout_seconds}s"
            logger.warning(f"⏱️ {service_name} health check timed out: {error_msg}")
            return 'down', response_time_ms, error_msg
        except httpx.ConnectError:
            response_time_ms = int((time.time() - start_time) * 1000)
            error_msg = "Connection refused"
            logger.warning(f"❌ {service_name} health check failed: {error_msg}")
            return 'down', response_time_ms, error_msg
        except Exception as e:
            response_time_ms = int((time.time() - start_time) * 1000)
            error_msg = str(e)
            logger.warning(f"❌ {service_name} health check failed: {error_msg}")
            return 'down', response_time_ms, error_msg

    @staticmethod
    async def check_all_services() -> Dict[str, Dict[str, Any]]:
        """
        Check health of all services.

        Returns: Dict with service status and metadata.
        """
        results = {}

        # Check all services concurrently
        tasks = [
            HealthMonitoringService.check_service(service_name, service_config)
            for service_name, service_config in HealthMonitoringService.SERVICES.items()
        ]

        statuses = await asyncio.gather(*tasks, return_exceptions=True)

        # Process results
        for (service_name, _), status_tuple in zip(
            HealthMonitoringService.SERVICES.items(),
            statuses
        ):
            if isinstance(status_tuple, Exception):
                status, response_time_ms, error_msg = 'down', None, str(status_tuple)
            else:
                status, response_time_ms, error_msg = status_tuple

            results[service_name] = {
                'status': status,
                'response_time_ms': response_time_ms,
                'error_message': error_msg,
                'checked_at': datetime.utcnow(),
            }

            # Log results
            if status == 'healthy':
                logger.info(f"✅ {service_name}: {status} ({response_time_ms}ms)")
            elif status == 'degraded':
                logger.warning(f"⚠️ {service_name}: {status} - {error_msg}")
            else:
                logger.error(f"❌ {service_name}: {status} - {error_msg}")

            # Store in database
            try:
                await HealthDAO.insert_health_check(
                    service_name=service_name,
                    status=status,
                    response_time_ms=response_time_ms,
                    timestamp=results[service_name]['checked_at'],
                    error_message=error_msg,
                    metadata={'endpoint': HealthMonitoringService.SERVICES[service_name]['endpoint']}
                )
            except Exception as e:
                logger.error(f"Failed to store health check for {service_name}: {e}")

        return results

    @staticmethod
    async def get_all_services_status() -> Dict[str, Any]:
        """Get the current status of all services."""
        latest_checks = await HealthDAO.get_all_latest_checks()
        return {
            'timestamp': datetime.utcnow().isoformat(),
            'services': {check['service_name']: {
                'status': check['status'],
                'response_time_ms': check['response_time_ms'],
                'checked_at': check['checked_at'].isoformat() if check['checked_at'] else None,
                'error_message': check['error_message'],
            } for check in latest_checks}
        }

    @staticmethod
    async def calculate_uptime_report(
        days: int = 30
    ) -> Dict[str, Any]:
        """Calculate uptime report for all services."""
        from datetime import timedelta

        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=days)

        uptime_data = await HealthDAO.get_all_services_uptime(start_date, end_date)

        # Calculate average uptime across all services
        if uptime_data:
            average_uptime = sum(uptime_data.values()) / len(uptime_data)
        else:
            average_uptime = 0.0

        return {
            'period': f"{days} days",
            'start_date': start_date.isoformat(),
            'end_date': end_date.isoformat(),
            'average_uptime_percentage': round(average_uptime, 2),
            'services': {
                service_name: round(uptime, 2)
                for service_name, uptime in uptime_data.items()
            }
        }
