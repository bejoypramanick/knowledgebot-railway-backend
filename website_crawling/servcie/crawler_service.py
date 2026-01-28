"""
Crawler Service Layer
Provides business logic for website crawling operations
"""
import logging
from typing import List, Optional, Dict, Any
from ..dao.scraping_dao import ScrapingDAO
from shared.db import get_db_connection

logger = logging.getLogger(__name__)

class CrawlerService:
    """Service layer for website crawling"""
    
    def __init__(self, scraping_dao: ScrapingDAO):
        self.scraping_dao = scraping_dao
    
    async def get_existing_website(self, url: str) -> Optional[Dict[str, Any]]:
        """Get existing website record"""
        try:
            return await self.scraping_dao.get_existing_website(url)
        except Exception as e:
            logger.error(f"Error fetching existing website: {e}")
            raise
    
    async def delete_website_record(self, url: str) -> bool:
        """Delete website record"""
        try:
            await self.scraping_dao.delete_website_record(url)
            logger.info(f"Website record deleted: {url}")
            return True
        except Exception as e:
            logger.error(f"Error deleting website record: {e}")
            raise
    
    async def record_scraped_metadata(self, metadata: Dict[str, Any]) -> str:
        """Record scraped metadata"""
        try:
            record_id = await self.scraping_dao.record_scraped_metadata(metadata)
            logger.info(f"Scraped metadata recorded: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Error recording scraped metadata: {e}")
            raise
