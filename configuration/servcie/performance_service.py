"""
Performance Service Layer
Provides business logic for performance metrics operations
"""
import logging
from typing import List, Optional, Dict, Any
from ..dao.performance_dao import PerformanceDAO
from shared.db import get_db_connection

logger = logging.getLogger(__name__)

class PerformanceService:
    """Service layer for performance metrics"""
    
    @classmethod
    async def get_performance_metrics(cls) -> Dict[str, Any]:
        """Get performance metrics"""
        async with get_db_connection() as conn:
            performance_dao = PerformanceDAO(conn)
            try:
                return await performance_dao.get_performance_metrics()
            except Exception as e:
                logger.error(f"Error fetching performance metrics: {e}")
                raise
    
    @classmethod
    async def get_chat_statistics(cls) -> Dict[str, Any]:
        """Get chat statistics"""
        async with get_db_connection() as conn:
            performance_dao = PerformanceDAO(conn)
            try:
                return await performance_dao.get_chat_statistics()
            except Exception as e:
                logger.error(f"Error fetching chat statistics: {e}")
                raise
