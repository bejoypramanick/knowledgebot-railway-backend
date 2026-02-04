"""
Scraping Data Access Object for Website Crawling
Handles database operations for web scraping
"""
from typing import Dict, List, Any, Optional
from website_crawling.core.db import get_db_connection
from website_crawling.core.otel_logger import get_otel_logger

logger = get_otel_logger("scraping_dao", "website-crawling")

class ScrapingDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_existing_website(self, url: str) -> Optional[Dict[str, Any]]:
        """Get existing website record"""
        query = """
            SELECT id, original_url as url, domain, title, description, gemini_state,
                   pages_scraped, content_length, created_at, updated_at
            FROM scraped_websites
            WHERE original_url = $1
            ORDER BY created_at DESC
            LIMIT 1
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, url)
                logger.log_db_query(query, {"url": url}, result)
                return result
        except Exception as e:
            logger.log_db_query(query, {"url": url}, error=e)
            return None

    async def delete_website_record(self, url: str) -> bool:
        """Delete website record"""
        query = """
            DELETE FROM scraped_websites
            WHERE original_url = $1
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, url)
                logger.log_db_query(query, {"url": url}, result)
                logger.info(f"Website record deleted: {url}")
                return True
        except Exception as e:
            logger.log_db_query(query, {"url": url}, error=e)
            raise

    async def record_scraped_metadata(self, metadata: Dict[str, Any]) -> str:
        """Record scraped metadata"""
        query = """
            INSERT INTO scraped_websites
            (user_role_id, original_url, domain, title, description, gemini_state,
             gemini_file_name, gemini_file_uri, pages_scraped, content_length, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW(), NOW())
            RETURNING id
        """
        params = [
            metadata.get('user_role_id'),
            metadata.get('url'),
            metadata.get('domain'),
            metadata.get('title'),
            metadata.get('description'),
            metadata.get('status', 'completed'),
            metadata.get('gemini_file_name'),
            metadata.get('gemini_file_uri'),
            metadata.get('pages_scraped', 1),
            metadata.get('content_length', 0)
        ]
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, *params)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise
