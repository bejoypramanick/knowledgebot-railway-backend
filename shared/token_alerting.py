"""
Token Tracking Alerting System
Provides alerting for high error rates and performance issues
"""
import asyncio
import json
import logging
import time
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Dict, List, Optional

from shared.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class AlertSeverity(Enum):
    """Alert severity levels"""
    LOW = "low"
    MEDIUM = "medium"
    HIGH = "high"
    CRITICAL = "critical"

class AlertType(Enum):
    """Types of alerts"""
    HIGH_ERROR_RATE = "high_error_rate"
    PERFORMANCE_DEGRADATION = "performance_degradation"
    SERVICE_UNAVAILABLE = "service_unavailable"
    TOKEN_VOLUME_SPIKE = "token_volume_spike"

@dataclass
class Alert:
    """Alert data structure"""
    alert_type: AlertType
    severity: AlertSeverity
    message: str
    operation: str
    current_value: float
    threshold: float
    timestamp: float
    metadata: Dict[str, Any]
    
    def to_dict(self) -> Dict[str, Any]:
        """Convert alert to dictionary for serialization"""
        return {
            "alert_type": self.alert_type.value,
            "severity": self.severity.value,
            "message": self.message,
            "operation": self.operation,
            "current_value": self.current_value,
            "threshold": self.threshold,
            "timestamp": self.timestamp,
            "metadata": self.metadata,
            "formatted_time": datetime.fromtimestamp(self.timestamp).isoformat()
        }

class AlertChannel:
    """Base class for alert channels"""
    
    async def send_alert(self, alert: Alert) -> bool:
        """Send alert to this channel"""
        raise NotImplementedError

class LogAlertChannel(AlertChannel):
    """Log-based alert channel"""
    
    def __init__(self, logger_name: str = "token_alerts"):
        self.alert_logger = logging.getLogger(logger_name)
    
    async def send_alert(self, alert: Alert) -> bool:
        """Send alert to logs"""
        try:
            log_message = f"ALERT [{alert.severity.value.upper()}] {alert.message}"
            if alert.severity == AlertSeverity.CRITICAL:
                self.alert_logger.critical(log_message)
            elif alert.severity == AlertSeverity.HIGH:
                self.alert_logger.error(log_message)
            elif alert.severity == AlertSeverity.MEDIUM:
                self.alert_logger.warning(log_message)
            else:
                self.alert_logger.info(log_message)
            
            self.alert_logger.info(f"Alert details: {json.dumps(alert.to_dict(), indent=2)}")
            return True
        except Exception as e:
            logger.error(f"Failed to send log alert: {e}")
            return False

class WebhookAlertChannel(AlertChannel):
    """Webhook-based alert channel"""
    
    def __init__(self, webhook_url: str, timeout: float = 10.0):
        self.webhook_url = webhook_url
        self.timeout = timeout
    
    async def send_alert(self, alert: Alert) -> bool:
        """Send alert via webhook"""
        try:
            import httpx
            
            async with httpx.AsyncClient(timeout=self.timeout) as client:
                response = await client.post(
                    self.webhook_url,
                    json=alert.to_dict(),
                    headers={"Content-Type": "application/json"}
                )
                response.raise_for_status()
                return True
        except Exception as e:
            logger.error(f"Failed to send webhook alert: {e}")
            return False

class EmailAlertChannel(AlertChannel):
    """Email-based alert channel (placeholder implementation)"""
    
    def __init__(self, smtp_config: Dict[str, Any], recipients: List[str]):
        self.smtp_config = smtp_config
        self.recipients = recipients
    
    async def send_alert(self, alert: Alert) -> bool:
        """Send alert via email"""
        # Placeholder for email implementation
        logger.info(f"Email alert would be sent to {self.recipients}: {alert.message}")
        return True

class TokenAlertManager:
    """Manages token tracking alerts"""
    
    def __init__(self):
        self.channels: List[AlertChannel] = []
        self.alert_history: List[Alert] = []
        self.alert_cooldowns: Dict[str, float] = {}
        self.cooldown_period = 300  # 5 minutes cooldown per alert type
        self._lock = asyncio.Lock()
    
    def add_channel(self, channel: AlertChannel):
        """Add an alert channel"""
        self.channels.append(channel)
    
    def remove_channel(self, channel: AlertChannel):
        """Remove an alert channel"""
        if channel in self.channels:
            self.channels.remove(channel)
    
    async def send_alert(self, alert: Alert) -> bool:
        """Send alert through all channels"""
        async with self._lock:
            # Check cooldown
            cooldown_key = f"{alert.alert_type.value}_{alert.operation}"
            current_time = time.time()
            
            if cooldown_key in self.alert_cooldowns:
                if current_time - self.alert_cooldowns[cooldown_key] < self.cooldown_period:
                    logger.debug(f"Alert {cooldown_key} is in cooldown period")
                    return False
            
            # Update cooldown
            self.alert_cooldowns[cooldown_key] = current_time
            
            # Store in history
            self.alert_history.append(alert)
            
            # Keep only last 1000 alerts
            if len(self.alert_history) > 1000:
                self.alert_history = self.alert_history[-1000:]
            
            # Send through all channels
            success_count = 0
            for channel in self.channels:
                try:
                    if await channel.send_alert(alert):
                        success_count += 1
                except Exception as e:
                    logger.error(f"Alert channel failed: {e}")
            
            logger.info(f"Alert sent to {success_count}/{len(self.channels)} channels")
            return success_count > 0
    
    async def check_error_rate_alert(self, operation: str, error_rate: float, threshold: float = 10.0):
        """Check if error rate exceeds threshold"""
        if error_rate > threshold:
            severity = AlertSeverity.CRITICAL if error_rate > 50.0 else AlertSeverity.HIGH
            if error_rate > 25.0:
                severity = AlertSeverity.CRITICAL
            elif error_rate > 15.0:
                severity = AlertSeverity.HIGH
            elif error_rate > 10.0:
                severity = AlertSeverity.MEDIUM
            
            alert = Alert(
                alert_type=AlertType.HIGH_ERROR_RATE,
                severity=severity,
                message=f"High error rate detected for {operation}: {error_rate:.1f}%",
                operation=operation,
                current_value=error_rate,
                threshold=threshold,
                timestamp=time.time(),
                metadata={
                    "threshold_type": "percentage",
                    "recommended_action": "Check service health and database connectivity"
                }
            )
            await self.send_alert(alert)
    
    async def check_performance_alert(self, operation: str, avg_response_time: float, threshold: float = 1000.0):
        """Check if response time exceeds threshold"""
        if avg_response_time > threshold:
            severity = AlertSeverity.CRITICAL if avg_response_time > 5000.0 else AlertSeverity.HIGH
            if avg_response_time > 5000.0:
                severity = AlertSeverity.CRITICAL
            elif avg_response_time > 2000.0:
                severity = AlertSeverity.HIGH
            elif avg_response_time > 1000.0:
                severity = AlertSeverity.MEDIUM
            
            alert = Alert(
                alert_type=AlertType.PERFORMANCE_DEGRADATION,
                severity=severity,
                message=f"Performance degradation detected for {operation}: {avg_response_time:.1f}ms average response time",
                operation=operation,
                current_value=avg_response_time,
                threshold=threshold,
                timestamp=time.time(),
                metadata={
                    "threshold_type": "milliseconds",
                    "recommended_action": "Check database performance and resource utilization"
                }
            )
            await self.send_alert(alert)
    
    async def check_service_availability(self, operation: str, last_success_time: Optional[float], threshold_minutes: float = 5.0):
        """Check if service has been unavailable"""
        if last_success_time is None:
            return
        
        current_time = time.time()
        time_since_success = current_time - last_success_time
        threshold_seconds = threshold_minutes * 60
        
        if time_since_success > threshold_seconds:
            severity = AlertSeverity.CRITICAL if time_since_success > threshold_seconds * 3 else AlertSeverity.HIGH
            
            alert = Alert(
                alert_type=AlertType.SERVICE_UNAVAILABLE,
                severity=severity,
                message=f"Service {operation} appears to be unavailable for {time_since_success/60:.1f} minutes",
                operation=operation,
                current_value=time_since_success,
                threshold=threshold_seconds,
                timestamp=current_time,
                metadata={
                    "threshold_type": "seconds",
                    "last_success_time": last_success_time,
                    "recommended_action": "Check service status and restart if necessary"
                }
            )
            await self.send_alert(alert)
    
    async def get_recent_alerts(self, hours: int = 24, severity: Optional[AlertSeverity] = None) -> List[Dict[str, Any]]:
        """Get recent alerts"""
        cutoff_time = time.time() - (hours * 3600)
        recent_alerts = [
            alert.to_dict() for alert in self.alert_history
            if alert.timestamp > cutoff_time and (severity is None or alert.severity == severity)
        ]
        return recent_alerts
    
    async def get_alert_summary(self, hours: int = 24) -> Dict[str, Any]:
        """Get alert summary for the specified period"""
        cutoff_time = time.time() - (hours * 3600)
        recent_alerts = [alert for alert in self.alert_history if alert.timestamp > cutoff_time]
        
        summary = {
            "total_alerts": len(recent_alerts),
            "by_severity": {},
            "by_type": {},
            "by_operation": {},
            "period_hours": hours
        }
        
        for alert in recent_alerts:
            # Count by severity
            severity_key = alert.severity.value
            summary["by_severity"][severity_key] = summary["by_severity"].get(severity_key, 0) + 1
            
            # Count by type
            type_key = alert.alert_type.value
            summary["by_type"][type_key] = summary["by_type"].get(type_key, 0) + 1
            
            # Count by operation
            summary["by_operation"][alert.operation] = summary["by_operation"].get(alert.operation, 0) + 1
        
        return summary

# Global alert manager instance
_alert_manager: Optional[TokenAlertManager] = None

def get_alert_manager() -> TokenAlertManager:
    """Get or create the global alert manager"""
    global _alert_manager
    if _alert_manager is None:
        _alert_manager = TokenAlertManager()
        # Add default log channel
        _alert_manager.add_channel(LogAlertChannel())
    return _alert_manager

async def setup_default_alerting(webhook_url: Optional[str] = None, email_config: Optional[Dict[str, Any]] = None):
    """Setup default alerting configuration"""
    alert_manager = get_alert_manager()
    
    # Add webhook channel if provided
    if webhook_url:
        alert_manager.add_channel(WebhookAlertChannel(webhook_url))
    
    # Add email channel if provided
    if email_config and email_config.get("recipients"):
        alert_manager.add_channel(EmailAlertChannel(
            email_config.get("smtp_config", {}),
            email_config["recipients"]
        ))

async def check_and_send_alerts(metrics: Dict[str, Any]):
    """Check metrics and send alerts if necessary"""
    alert_manager = get_alert_manager()
    
    for operation, operation_metrics in metrics.items():
        # Check error rate
        if "error_rate" in operation_metrics:
            await alert_manager.check_error_rate_alert(
                operation, 
                operation_metrics["error_rate"]
            )
        
        # Check performance
        if "average_response_time_ms" in operation_metrics:
            await alert_manager.check_performance_alert(
                operation,
                operation_metrics["average_response_time_ms"]
            )
        
        # Check service availability
        if "last_success_timestamp" in operation_metrics:
            await alert_manager.check_service_availability(
                operation,
                operation_metrics["last_success_timestamp"]
            )
