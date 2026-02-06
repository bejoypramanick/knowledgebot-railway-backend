"""Health Reporting Service for generating reports."""
import logging
from datetime import datetime, timedelta
from typing import Dict, Any, List

from health_monitoring.dao.health_dao import HealthDAO

logger = logging.getLogger(__name__)


class HealthReporterService:
    """Service for generating health reports."""

    @staticmethod
    async def generate_24x7_availability_report() -> Dict[str, Any]:
        """Generate 24/7 availability report for the system."""
        # Get uptime for last 30 days
        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)

        uptime_data = await HealthDAO.get_all_services_uptime(start_date, end_date)

        if uptime_data:
            average_uptime = sum(uptime_data.values()) / len(uptime_data)
            status = 'excellent' if average_uptime >= 99.9 else 'good' if average_uptime >= 95 else 'needs_attention'
        else:
            average_uptime = 0.0
            status = 'no_data'

        return {
            'type': '24x7_availability',
            'period': 'last_30_days',
            'average_uptime_percentage': round(average_uptime, 2),
            'status': status,
            'generated_at': datetime.utcnow().isoformat(),
            'services': {
                service_name: round(uptime, 2)
                for service_name, uptime in uptime_data.items()
            }
        }

    @staticmethod
    async def generate_monthly_traffic_report(month_offset: int = 0) -> Dict[str, Any]:
        """Generate monthly traffic report."""
        now = datetime.utcnow()
        current_month_start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)

        # Adjust for month offset (negative = previous months)
        for _ in range(month_offset):
            if current_month_start.month == 1:
                current_month_start = current_month_start.replace(
                    year=current_month_start.year - 1,
                    month=12
                )
            else:
                current_month_start = current_month_start.replace(
                    month=current_month_start.month - 1
                )

        # Calculate next month start
        if current_month_start.month == 12:
            next_month_start = current_month_start.replace(
                year=current_month_start.year + 1,
                month=1
            )
        else:
            next_month_start = current_month_start.replace(
                month=current_month_start.month + 1
            )

        return {
            'type': 'monthly_traffic',
            'month': current_month_start.strftime('%B %Y'),
            'period_start': current_month_start.isoformat(),
            'period_end': next_month_start.isoformat(),
            'generated_at': datetime.utcnow().isoformat(),
            'note': 'Traffic metrics are tracked separately in chat_sessions table'
        }

    @staticmethod
    async def generate_uptime_chart_data(
        service_name: str = None,
        interval: str = 'day',
        days: int = 30
    ) -> Dict[str, Any]:
        """Generate data for uptime charts."""
        data = await HealthDAO.get_uptime_over_time(service_name, interval)

        return {
            'type': 'uptime_chart_data',
            'service': service_name or 'all_services',
            'interval': interval,
            'period_days': days,
            'data': data,
            'generated_at': datetime.utcnow().isoformat(),
        }

    @staticmethod
    async def generate_system_health_summary() -> Dict[str, Any]:
        """Generate overall system health summary."""
        # Get latest checks for all services
        latest_checks = await HealthDAO.get_all_latest_checks()

        healthy_count = sum(1 for check in latest_checks if check['status'] == 'healthy')
        degraded_count = sum(1 for check in latest_checks if check['status'] == 'degraded')
        down_count = sum(1 for check in latest_checks if check['status'] == 'down')
        total_services = len(latest_checks)

        # Determine overall health
        if down_count > 0:
            overall_status = 'critical'
        elif degraded_count > 0:
            overall_status = 'warning'
        else:
            overall_status = 'healthy'

        # Get recent failures
        recent_failures = await HealthDAO.get_recent_failures(limit=5)

        return {
            'type': 'system_health_summary',
            'overall_status': overall_status,
            'services': {
                'healthy': healthy_count,
                'degraded': degraded_count,
                'down': down_count,
                'total': total_services
            },
            'health_percentage': round((healthy_count / total_services * 100) if total_services > 0 else 0, 1),
            'recent_failures': [
                {
                    'service': failure['service_name'],
                    'status': failure['status'],
                    'error': failure['error_message'],
                    'checked_at': failure['checked_at'].isoformat() if failure['checked_at'] else None,
                }
                for failure in recent_failures
            ],
            'generated_at': datetime.utcnow().isoformat(),
        }

    @staticmethod
    async def generate_sla_compliance_report() -> Dict[str, Any]:
        """Generate SLA compliance report (99.5% uptime target)."""
        SLA_TARGET = 99.5  # 99.5% uptime

        end_date = datetime.utcnow()
        start_date = end_date - timedelta(days=30)

        uptime_data = await HealthDAO.get_all_services_uptime(start_date, end_date)

        sla_status = {}
        compliant_services = 0

        for service_name, uptime in uptime_data.items():
            is_compliant = uptime >= SLA_TARGET
            sla_status[service_name] = {
                'uptime': round(uptime, 2),
                'target': SLA_TARGET,
                'compliant': is_compliant,
                'deficit': round(SLA_TARGET - uptime, 2) if not is_compliant else 0
            }
            if is_compliant:
                compliant_services += 1

        compliance_percentage = (compliant_services / len(uptime_data) * 100) if uptime_data else 0

        return {
            'type': 'sla_compliance_report',
            'sla_target': f"{SLA_TARGET}%",
            'period': '30_days',
            'compliance_percentage': round(compliance_percentage, 1),
            'services': sla_status,
            'generated_at': datetime.utcnow().isoformat(),
        }
