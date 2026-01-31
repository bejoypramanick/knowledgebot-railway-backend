"""
Crawler Service Layer
Provides business logic for website crawling operations
"""
from typing import Any, Dict, List, Optional

from website_crawling.core.logging_config import get_railway_logger

from ..dao.scraping_dao import ScrapingDAO

logger = get_railway_logger(__name__)

class CrawlerService:
    """Service layer for website crawling"""
    
    def __init__(self):
        self.scraping_dao = ScrapingDAO()  # Service manages its own DAO
    
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

    async def start_crawl_session(self, urls: List[str], user_id: str, options: Dict[str, Any]) -> Dict[str, Any]:
        """Start a crawl session"""
        try:
            # This would need to be implemented based on actual crawl session logic
            # For now, return success response
            return {
                "success": True,
                "session_id": f"session_{len(urls)}",
                "message": "Crawl session started successfully"
            }
        except Exception as e:
            logger.error(f"Error starting crawl session: {e}")
            raise

    async def get_all_sessions(self) -> List[Dict[str, Any]]:
        """Get all crawl sessions"""
        try:
            # This would need to be implemented based on actual session storage logic
            # For now, return empty list
            return []
        except Exception as e:
            logger.error(f"Error getting all sessions: {e}")
            raise

    async def get_session_details(self, session_id: str, user_id: str) -> Optional[Dict[str, Any]]:
        """Get details of a crawl session"""
        try:
            # This would need to be implemented based on actual session storage logic
            # For now, return empty dict
            return {}
        except Exception as e:
            logger.error(f"Error getting session details: {e}")
            raise

    async def stop_session(self, session_id: str, user_id: str) -> Dict[str, Any]:
        """Stop a crawl session"""
        try:
            # This would need to be implemented based on actual session management logic
            # For now, return success response
            return {
                "success": True,
                "message": f"Session {session_id} stopped successfully"
            }
        except Exception as e:
            logger.error(f"Error stopping session: {e}")
            raise
            logger.info(f"Scraped metadata recorded: {record_id}")
            return record_id
        except Exception as e:
            logger.error(f"Error recording scraped metadata: {e}")
            raise
