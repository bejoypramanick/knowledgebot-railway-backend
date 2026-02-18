"""
Website Service for Celery Website Crawling Worker
Handles business logic for website crawling operations
"""
from typing import Dict, List, Any, Optional
from ..dao.scraping_dao import ScrapingDAO
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("website_service", "celery-web-worker")

class WebsiteService:
    def __init__(self):
        self.scraping_dao = ScrapingDAO()

    async def get_website_by_id(self, website_id: int) -> Optional[Dict[str, Any]]:
        """Get website by ID."""
        return await self.scraping_dao.get_website_by_id(website_id)

    async def update_website_status(self, website_id: int, status: str, error_message: str = None):
        """Update website processing status."""
        try:
            await self.scraping_dao.update_website_status(website_id, status, error_message)
            logger.info(f"✅ Updated website {website_id} status to {status}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to update website {website_id} status: {e}")
            return False

    async def get_all_websites(self) -> List[Dict[str, Any]]:
        """Get all website records."""
        return await self.scraping_dao.get_all_websites()

    async def delete_website_record(self, url: str):
        """Delete website record."""
        try:
            await self.scraping_dao.delete_website_record(url)
            logger.info(f"✅ Deleted website record for {url}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to delete website record for {url}: {e}")
            return False

    async def create_website_record(self, website_data: Dict[str, Any]) -> Optional[int]:
        """Create new website record."""
        try:
            website_id = await self.scraping_dao.record_scraped_metadata(website_data)
            if website_id:
                logger.info(f"✅ Created website record {website_id}")
                return website_id
            else:
                logger.error("❌ Failed to create website record")
                return None
        except Exception as e:
            logger.error(f"❌ Error creating website record: {e}")
            return None
