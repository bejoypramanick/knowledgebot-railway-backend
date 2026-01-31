"""
Scraping Data Access Object for Website Crawling
Handles database operations for web scraping
"""
import logging
from typing import Dict, List, Any, Optional
from website_crawling.core.db import get_db_connection

logger = logging.getLogger("scraping_dao")

class ScrapingDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_existing_website(self, url: str) -> Optional[Dict[str, Any]]:
        """Get existing website record"""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchrow("""
                    SELECT id, url, domain, title, description, status, 
                           pages_scraped, content_length, created_at, updated_at
                    FROM scraped_websites
                    WHERE url = $1
                    ORDER BY created_at DESC
                    LIMIT 1
                """, url)
        except Exception as e:
            logger.error(f"Error fetching existing website: {e}")
            raise

    async def delete_website_record(self, url: str) -> bool:
        """Delete website record"""
        try:
            async with get_db_connection() as conn:
                result = await conn.execute("""
                    DELETE FROM scraped_websites 
                    WHERE url = $1
                """, url)
                logger.info(f"Website record deleted: {url}")
                return True
        except Exception as e:
            logger.error(f"Error deleting website record: {e}")
            raise

    async def record_scraped_metadata(self, metadata: Dict[str, Any]) -> str:
        """Record scraped metadata"""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchval("""
                    INSERT INTO scraped_websites 
                    (url, domain, title, description, status, 
                     pages_scraped, content_length, created_at, updated_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, NOW(), NOW())
                    RETURNING id
                """, 
                    metadata.get('url'),
                    metadata.get('domain'),
                    metadata.get('title'),
                    metadata.get('description'),
                    metadata.get('status', 'completed'),
                    metadata.get('pages_scraped', 1),
                    metadata.get('content_length', 0)
                )
        except Exception as e:
            logger.error(f"Error recording scraped metadata: {e}")
            raise
