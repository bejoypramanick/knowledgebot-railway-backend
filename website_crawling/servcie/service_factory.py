"""
Service Factory for Website Crawling
Handles all database connections internally for crawler services
"""
import logging
from shared.db import get_db_connection

logger = logging.getLogger(__name__)

class ServiceFactory:
    """Factory for creating service instances with proper DAO injection"""
    
    @staticmethod
    async def create_crawler_service():
        """Create CrawlerService with ScrapingDAO"""
        from ..servcie.crawler_service import CrawlerService
        from ..dao.scraping_dao import ScrapingDAO
        
        async with get_db_connection() as conn:
            scraping_dao = ScrapingDAO(conn)
            return CrawlerService(scraping_dao)
