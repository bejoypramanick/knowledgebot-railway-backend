"""
Token Metrics Endpoints
Provides API endpoints for monitoring token tracking metrics and health status
"""
from fastapi import APIRouter, HTTPException, Depends, Query, Request
from typing import Optional, Dict, Any
from shared.logging_config import get_railway_logger
import logging

from shared.auth_middleware import get_current_user
from shared.token_metrics import (
    get_token_tracking_metrics,
    get_token_tracking_health
)
from shared.rate_limiter import rate_limit_metrics
from shared.token_alerting import get_alert_manager, AlertSeverity, setup_default_alerting

# Initialize alerting on module import
async def init_alerting():
    """Initialize default alerting configuration"""
    # You can configure webhook URL and email settings here
    webhook_url = None  # Set your webhook URL in environment variables
    email_config = None  # Set your email config in environment variables
    
    await setup_default_alerting(webhook_url, email_config)

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["token-metrics"])


@router.get("/token-metrics", response_model=dict)
@rate_limit_metrics
async def get_token_metrics(
    request: Request,
    operation: Optional[str] = Query(None, description="Specific operation to get metrics for"),
    current_user: dict = Depends(get_current_user)
):
    """Get token tracking metrics"""
    try:
        metrics = await get_token_tracking_metrics(operation)
        
        # Check for alert conditions
        from shared.token_alerting import check_and_send_alerts
        await check_and_send_alerts(metrics)
        
        return {
            "success": True,
            "data": metrics
        }
    except Exception as e:
        logger.error(f"Error getting token metrics: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve token metrics")


@router.get("/token-metrics/health", response_model=dict)
@rate_limit_metrics
async def get_token_health_status(
    request: Request,
    current_user: dict = Depends(get_current_user)
):
    """Get token tracking system health status"""
    try:
        health = await get_token_tracking_health()
        return {
            "success": True,
            "data": health
        }
    except Exception as e:
        logger.error(f"Error getting token health status: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve health status")


@router.get("/token-metrics/alerts", response_model=dict)
@rate_limit_metrics
async def get_token_alerts(
    request: Request,
    hours: int = Query(24, description="Hours of alert history to retrieve"),
    severity: Optional[str] = Query(None, description="Filter by alert severity"),
    current_user: dict = Depends(get_current_user)
):
    """Get recent token tracking alerts"""
    try:
        alert_manager = get_alert_manager()
        
        # Parse severity filter
        severity_filter = None
        if severity:
            try:
                severity_filter = AlertSeverity(severity.lower())
            except ValueError:
                raise HTTPException(status_code=400, detail=f"Invalid severity: {severity}")
        
        alerts = await alert_manager.get_recent_alerts(hours, severity_filter)
        
        return {
            "success": True,
            "data": {
                "alerts": alerts,
                "count": len(alerts),
                "hours": hours
            }
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting token alerts: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve alerts")


@router.get("/token-metrics/alerts/summary", response_model=dict)
@rate_limit_metrics
async def get_token_alerts_summary(
    request: Request,
    hours: int = Query(24, description="Hours for alert summary"),
    current_user: dict = Depends(get_current_user)
):
    """Get token tracking alerts summary"""
    try:
        alert_manager = get_alert_manager()
        summary = await alert_manager.get_alert_summary(hours)
        
        return {
            "success": True,
            "data": summary
        }
    except Exception as e:
        logger.error(f"Error getting token alerts summary: {e}")
        raise HTTPException(status_code=500, detail="Failed to retrieve alert summary")
