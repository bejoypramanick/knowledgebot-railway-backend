"""
Performance Service Layer
Provides business logic for performance metrics operations
"""
from typing import Any, Dict

from configuration.core.logging_config import get_railway_logger

from ..dao.performance_dao import PerformanceDAO

logger = get_railway_logger(__name__)

class PerformanceService:
    """Service layer for performance metrics"""
    
    def __init__(self):
        self.performance_dao = PerformanceDAO()  # Service manages its own DAO
    
    async def get_performance_metrics(self) -> Dict[str, Any]:
        """Get performance metrics"""
        try:
            return await self.performance_dao.get_performance_metrics()
        except Exception as e:
            logger.error(f"Error fetching performance metrics: {e}")
            raise
