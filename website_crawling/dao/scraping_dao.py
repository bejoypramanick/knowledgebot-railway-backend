"""
Scraping Data Access Object for Website Crawling
Handles database operations for web scraping
"""
from typing import Dict, List, Any, Optional
from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("scraping_dao", "website-crawling")

class ScrapingDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_existing_website(self, url: str) -> Optional[Dict[str, Any]]:
        """Get existing website record that is active (not cancelled/failed)"""
        query = """
            SELECT id, original_url as url, domain, title, description, gemini_state,
                   pages_scraped, content_length, processing_status, created_at, updated_at,
                   metadata
            FROM scraped_websites
            WHERE original_url = $1
              AND processing_status NOT IN ('cancelled', 'failed')
            ORDER BY created_at DESC
            LIMIT 1
        """
        params = {"url": url}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, url)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def delete_website_record(self, url: str) -> bool:
        """Delete website record"""
        query = """
            DELETE FROM scraped_websites
            WHERE original_url = $1
        """
        params = {"url": url}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, url)
                logger.log_db_query(query, params, result)
                return True
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def record_scraped_metadata(self, metadata: Dict[str, Any]) -> str:
        """Record scraped metadata including FileSearch metadata for deletion"""
        import json

        query = """
            INSERT INTO scraped_websites
            (user_role_id, original_url, domain, title, description, gemini_state,
             gemini_file_name, gemini_file_uri, pages_scraped, content_length, metadata,
             parent_id, depth, crawl_session_id, celery_task_id, created_at, updated_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11::jsonb, $12, $13, $14, $15, NOW(), NOW())
            RETURNING id
        """

        # Extract FileSearch metadata if available
        file_search_metadata = metadata.get('file_search_metadata')
        metadata_json = json.dumps(file_search_metadata) if file_search_metadata else None

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
            metadata.get('content_length', 0),
            metadata_json,
            metadata.get('parent_id'),
            metadata.get('depth', 0),
            metadata.get('crawl_session_id'),
            metadata.get('celery_task_id')  # Store Celery task ID
        ]
        
        # DEBUG: Log parent_id value
        parent_id = metadata.get('parent_id')
        logger.info(f"🔍 [DEBUG] Inserting scraped metadata - URL: {metadata.get('url')}, parent_id: {parent_id}, depth: {metadata.get('depth')}")
        
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, *params)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

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
                result = await conn.execute(query, *params)
                logger.log_db_query(query, params, result)
        except Exception as e:
            logger.log_db_query(query, params, error=e)

    async def update_celery_task_id(self, website_id: int, celery_task_id: str):
        """Update Celery task ID for website."""
        query = """
            UPDATE scraped_websites 
            SET celery_task_id = $1::text, updated_at = NOW() 
            WHERE id = $2::int
        """
        params = [celery_task_id, website_id]
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, *params)
                logger.log_db_query(query, params, result)
        except Exception as e:
            logger.log_db_query(query, params, error=e)

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

    async def get_websites_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Get websites by processing status."""
        query = "SELECT * FROM scraped_websites WHERE processing_status = $1::text ORDER BY created_at DESC"
        params = {"status": status}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetch(status, params)
                logger.log_db_query(query, params, result)
                return [dict(row) for row in result] if result else []
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return []

    async def update_all_websites_status(self, from_status: str, to_status: str):
        """Update all websites with given status to new status."""
        query = """
            UPDATE scraped_websites 
            SET processing_status = $1::text, updated_at = NOW() 
            WHERE processing_status = $2::text
        """
        params = [to_status, from_status]
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, *params)
                logger.log_db_query(query, params, result)
        except Exception as e:
            logger.log_db_query(query, params, error=e)
