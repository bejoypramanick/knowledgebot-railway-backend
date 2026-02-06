"""API Router for health monitoring endpoints."""
import logging
from datetime import datetime
from typing import Optional

from fastapi import APIRouter, Query

from health_monitoring.service.health_monitoring_service import HealthMonitoringService
from health_monitoring.service.health_reporter_service import HealthReporterService

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/health")
async def self_health_check():
    """Health check endpoint for this service."""
    return {
        "status": "healthy",
        "service": "health-monitoring",
        "timestamp": datetime.utcnow().isoformat()
    }


@router.get("/services")
async def get_all_services_status():
    """Get current status of all monitored services."""
    return await HealthMonitoringService.get_all_services_status()


@router.get("/uptime")
async def get_uptime_report(
    days: Optional[int] = Query(30, ge=1, le=180),
    service: Optional[str] = Query(None)
):
    """
    Get uptime report for services.

    Query Parameters:
    - days: Number of days to include (1-90, default 30)
    - service: Specific service name (optional, returns all if not specified)
    """
    if service:
        from health_monitoring.dao.health_dao import HealthDAO
        uptime = await HealthDAO.get_uptime_by_service(service)
        return {
            "service": service,
            "days": days,
            "uptime_percentage": round(uptime, 2)
        }
    else:
        return await HealthMonitoringService.calculate_uptime_report(days)


@router.get("/chart-data")
async def get_uptime_chart_data(
    service: Optional[str] = Query(None),
    interval: Optional[str] = Query("day", regex="^(hour|day|week|month)$"),
    days: Optional[int] = Query(30, ge=1, le=180)
):
    """
    Get chart data for uptime visualization.

    Query Parameters:
    - service: Specific service name (optional)
    - interval: Time interval (hour, day, week, month - default: day)
    - days: Number of days to include (1-90, default 30)
    """
    return await HealthReporterService.generate_uptime_chart_data(
        service_name=service,
        interval=interval,
        days=days
    )


@router.get("/summary")
async def get_system_health_summary():
    """Get overall system health summary."""
    return await HealthReporterService.generate_system_health_summary()


@router.get("/availability")
async def get_24x7_availability_report():
    """Get 24/7 availability report for the system."""
    return await HealthReporterService.generate_24x7_availability_report()


@router.get("/sla-compliance")
async def get_sla_compliance_report():
    """Get SLA compliance report (99.5% target)."""
    return await HealthReporterService.generate_sla_compliance_report()


@router.get("/traffic")
async def get_monthly_traffic_report(month_offset: Optional[int] = Query(0, ge=-11, le=0)):
    """
    Get monthly traffic report.

    Query Parameters:
    - month_offset: Month offset from now (0=current, -1=last month, etc. range -11 to 0)
    """
    return await HealthReporterService.generate_monthly_traffic_report(month_offset)
