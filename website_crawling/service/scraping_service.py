"""
Scraping Service Layer for Website Crawling
Provides business logic for website scraping operations
"""
from typing import Any, Dict, Optional

from shared.logging_config import get_railway_logger

from ..core.ai import get_genai_client
from ..dao.scraping_dao import ScrapingDAO

logger = get_railway_logger(__name__)

class ScrapingService:
    """Service layer for website scraping operations"""
    
    def __init__(self):
        self.scraping_dao = ScrapingDAO()  # Service manages its own DAO
    
    async def get_existing_website(self, url: str, domain: str) -> Optional[Dict[str, Any]]:
        """Check if website already exists in database."""
        try:
            return await self.scraping_dao.find_existing_scraping(url)
        except Exception as e:
            logger.error(f"Error checking existing website: {e}")
            return None

    async def delete_website_record(self, record_id: str):
        """Delete a website record from database."""
        try:
            await self.scraping_dao.delete_scraping_record(record_id)
        except Exception as e:
            logger.error(f"Error deleting website record: {e}")

    async def delete_gemini_file(self, file_name: str):
        """Delete a file from Gemini storage."""
        genai_client = get_genai_client()
        if genai_client and file_name:
            try:
                genai_client.files.delete(name=file_name)
                logger.info(f"Deleted Gemini file: {file_name}")
            except Exception as e:
                logger.warning(f"Failed to delete Gemini file {file_name}: {e}")

    async def insert_scraped_metadata(self, metadata: dict):
        """Insert scraped metadata into database."""
        try:
            await self.scraping_dao.insert_scraped_metadata(metadata)
        except Exception as e:
            logger.error(f"Error inserting scraped metadata: {e}")
            raise

    async def handle_scrape_request(self, request, sse_queue=None) -> dict:
        """Handle scrape request with all business logic"""
        try:
            domain = urlparse(request.url).netloc.replace('www.', '')
            
            # Check existing
            existing = await self.get_existing_website(request.url, domain)
            version = 1
            
            if existing:
                if not request.replace_existing:
                    raise HTTPException(status_code=409, detail={
                        "message": f"Website already scraped (Version {existing['version']})",
                        "existing_url": existing['original_url'],
                        "version": existing['version'],
                        "suggestion": "Set replace_existing=true to re-scrape"
                    })
                else:
                    version = existing['version'] + 1
                    if existing['gemini_file_name']:
                        await self.delete_gemini_file(existing['gemini_file_name'])
                    await self.delete_website_record(existing['id'])
            
            return {"existing": existing, "version": version}
        except Exception as e:
            logger.error(f"Error handling scrape request: {e}")
            raise

# Singleton instance
