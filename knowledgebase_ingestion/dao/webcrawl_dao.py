"""
Web Crawl Data Access Object
Handles database operations for website scraping only
"""
from typing import Any, Dict, List, Optional
import json

from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("webcrawl_dao", "knowledgebase-ingestion")

class WebCrawlDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def create_website_record(self, url: str, user_email: str, task_id: str) -> Optional[int]:
        """Create website record with Queued status."""
        query = """
            INSERT INTO scraped_websites (original_url, processing_status, user_email, celery_task_id, created_at, updated_at)
            VALUES ($1, 'Queued', $2, $3, NOW(), NOW())
            RETURNING id
        """
        params = [url, user_email, task_id]
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, url, user_email, task_id)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def get_website_by_id(self, website_id: int) -> Optional[Dict[str, Any]]:
        """Get website record by ID."""
        query = """
            SELECT id, original_url, processing_status, error_message, created_at, updated_at
            FROM scraped_websites WHERE id = $1
        """
        params = {"website_id": website_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, website_id)
                logger.log_db_query(query, params, result)
                if result:
                    return {
                        "id": str(result['id']),
                        "original_url": result['original_url'],
                        "processing_status": result['processing_status'],
                        "error_message": result['error_message'],
                        "created_at": result['created_at'],
                        "updated_at": result['updated_at']
                    }
                return None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def get_all_websites(self) -> List[Dict[str, Any]]:
        """Get all websites with their status."""
        query = """
            SELECT id, original_url, processing_status, error_message, created_at, updated_at
            FROM scraped_websites
            ORDER BY updated_at DESC
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, result=result)
                return result
        except Exception as e:
            logger.log_db_query(query, error=e)
            return []

    async def get_pending_websites(self) -> List[Dict[str, Any]]:
        """Get all websites with pending or processing status."""
        query = """
            SELECT id, original_url, processing_status, error_message, created_at, updated_at
            FROM scraped_websites
            WHERE processing_status IN ('pending', 'processing')
            ORDER BY updated_at DESC
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, result=result)
                return result
        except Exception as e:
            logger.log_db_query(query, error=e)
            return []

    async def update_website_status(self, website_id: int, status: str, error_message: str = None) -> bool:
        """Update website processing status."""
        query = """
            UPDATE scraped_websites 
            SET processing_status = $2, error_message = $3, updated_at = NOW()
            WHERE id = $1
        """
        params = [status, error_message, website_id]
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, status, error_message, website_id)
                logger.log_db_query(query, params, result)
                return result != "UPDATE 0"
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False

    async def cancel_websites(self) -> int:
        """Cancel all pending/processing websites."""
        query = """
            UPDATE scraped_websites 
            SET processing_status = 'cancelled', updated_at = NOW()
            WHERE processing_status IN ('pending', 'processing')
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.execute(query)
                logger.log_db_query(query, result=result)
                return result
        except Exception as e:
            logger.log_db_query(query, error=e)
            return 0

    async def delete_website_by_id(self, website_id: int) -> bool:
        """Delete website record by ID."""
        query = "DELETE FROM scraped_websites WHERE id = $1"
        params = {"website_id": website_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, website_id)
                logger.log_db_query(query, params, result)
                return result != "DELETE 0"
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False

    async def update_celery_task_id(self, website_id: int, task_id: str) -> bool:
        """Update celery_task_id for a website record."""
        query = """
            UPDATE scraped_websites
            SET celery_task_id = $2, updated_at = NOW()
            WHERE id = $1
        """
        params = [website_id, task_id]
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, website_id, task_id)
                logger.log_db_query(query, params, result)
                return result != "UPDATE 0"
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False

    async def get_website_details_by_task_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get website details by celery_task_id for worker processing."""
        query = """
            SELECT id, original_url, processing_status, user_email, celery_task_id
            FROM scraped_websites 
            WHERE celery_task_id = $1
        """
        params = {"task_id": task_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, task_id)
                logger.log_db_query(query, params, result)
                if result:
                    return {
                        "website_id": result['id'],
                        "original_url": result['original_url'],
                        "processing_status": result['processing_status'],
                        "user_email": result['user_email'],
                        "celery_task_id": result['celery_task_id']
                    }
                return None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None
