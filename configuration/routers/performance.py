"""
Performance Metrics Endpoints
"""
from fastapi import APIRouter, HTTPException
from typing import Optional, Dict, Any, List
from datetime import datetime, timedelta
import logging
import sys
from pathlib import Path

# Add shared directory to path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["performance"])

from shared.auth_middleware import get_current_user
from ..servcie.performance_service import PerformanceService
from ..dao.performance_dao import PerformanceDAO


@router.get("/performance/metrics")
async def get_performance_metrics():
    """Get chatbot performance metrics from database with optimized parallel queries."""
    logger.info("Performance metrics endpoint called - starting optimized parallel queries")

    try:
        performance_dao = PerformanceDAO()
        service = PerformanceService(performance_dao)
        metrics = await service.get_performance_metrics()
        
        return metrics
    except Exception as e:
        logger.error(f"Error fetching performance metrics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching performance metrics: {str(e)}")


@router.get("/performance/chat-statistics")
async def get_chat_statistics():
    """Get detailed chat statistics."""
    try:
        performance_dao = PerformanceDAO()
        service = PerformanceService(performance_dao)
        stats = await service.get_chat_statistics()
        
        return stats
    except Exception as e:
        logger.error(f"Error fetching chat statistics: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error fetching chat statistics: {str(e)}")


@router.get("/performance/health")
async def health_check():
    """Health check endpoint for performance service."""
    try:
        performance_dao = PerformanceDAO()
        service = PerformanceService(performance_dao)
        # Test service health
        await service.get_performance_metrics()
        return {"status": "healthy", "database": "connected"}
    except Exception as e:
        logger.error(f"Performance health check failed: {e}")
        return {"status": "unhealthy", "database": "disconnected", "error": str(e)}
