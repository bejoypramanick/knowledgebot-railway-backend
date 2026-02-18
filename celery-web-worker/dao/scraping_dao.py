"""
Scraping DAO for Celery Website Crawling Worker
Handles database operations for website management
"""
from typing import Dict, List, Any, Optional
import json
from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("scraping_dao", "celery-web-worker")

class ScrapingDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_website_by_id(self, website_id: int) -> Optional[Dict[str, Any]]:
        """Get website record by ID."""
        query = "SELECT * FROM scraped_websites WHERE id = $1::int"
        params = {"website_id": website_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, website_id)
                logger.log_db_query(query, params, result)
                return dict(result) if result else None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def update_website_status(self, website_id: int, status: str, error_message: str = None):
        """Update website processing status."""
        query = """
            UPDATE scraped_websites 
            SET processing_status = $1::text, error_message = $2::text, updated_at = NOW() 
            WHERE id = $3::int
        """
        params = [status, error_message, website_id]
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, status, error_message, website_id)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def get_all_websites(self) -> List[Dict[str, Any]]:
        """Get all website records."""
        query = "SELECT * FROM scraped_websites ORDER BY created_at DESC"
        try:
            logger.log_db_operation(query, {})
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, {}, result)
                return [dict(row) for row in result] if result else []
        except Exception as e:
            logger.log_db_query(query, {}, error=e)
            return []

    async def delete_website_record(self, url: str):
        """Delete website record from database."""
        query = "DELETE FROM scraped_websites WHERE original_url = $1::text"
        params = {"url": url}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, url)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise
