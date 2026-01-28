"""
Service Factory for Knowledgebase Ingestion
Handles all database connections internally for ingestion services
"""
import logging
from shared.db import get_db_connection

logger = logging.getLogger(__name__)

class ServiceFactory:
    """Factory for creating service instances with proper DAO injection"""
    
    @staticmethod
    async def create_ingestion_service():
        """Create IngestionService with FileDAO"""
        from ..servcie.ingestion_service import IngestionService
        from ..dao.file_dao import FileDAO
        
        async with get_db_connection() as conn:
            file_dao = FileDAO(conn)
            return IngestionService(file_dao)
