"""
Web Crawl Service Layer
Handles business logic for website scraping operations
"""
import asyncio
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import HTTPException

from shared.otel_logger import get_otel_logger
from knowledgebase_ingestion.dao.webcrawl_dao import WebCrawlDAO
from shared.redis_message_queue import RedisMessageQueue
from shared.celery_dispatcher import web_celery

logger = get_otel_logger("webcrawl_service", "knowledgebase-ingestion")

# Singleton DAO instance
_webcrawl_dao = None

def get_webcrawl_dao() -> WebCrawlDAO:
    """Get singleton WebCrawlDAO instance."""
    global _webcrawl_dao
    if _webcrawl_dao is None:
        _webcrawl_dao = WebCrawlDAO()
    return _webcrawl_dao


async def create_website_record(url: str, user_role_id: int = None, task_id: str = None) -> Optional[int]:
    """
    Create website record with Queued status.
    Delegates to DAO layer for database operations.

    Args:
        url: Website URL to scrape
        user_role_id: User role ID (optional, for audit trail)
        task_id: Celery task ID
    """
    try:
        dao = get_webcrawl_dao()
        return await dao.create_website_record(url, user_role_id, task_id)
    except Exception as e:
        logger.error(f"❌ Error creating website record: {e}")
        return None


async def get_pending_websites() -> List[Dict[str, Any]]:
    """Get all websites with pending or processing status."""
    try:
        dao = get_webcrawl_dao()
        return await dao.get_pending_websites()
    except Exception as e:
        logger.error(f"❌ Error getting pending websites: {e}")
        return []


async def get_website_by_id(website_id: int) -> Optional[Dict[str, Any]]:
    """Get website record by ID."""
    try:
        dao = get_webcrawl_dao()
        return await dao.get_website_by_id(website_id)
    except Exception as e:
        logger.error(f"❌ Error getting website by ID: {e}")
        return None


async def cancel_websites() -> int:
    """Cancel all pending/processing websites."""
    try:
        dao = get_webcrawl_dao()
        return await dao.cancel_websites()
    except Exception as e:
        logger.error(f"❌ Error cancelling websites: {e}")
        return 0


async def update_website_status(website_id: int, status: str, error_message: str = None) -> bool:
    """Update website processing status."""
    try:
        dao = get_webcrawl_dao()
        return await dao.update_website_status(website_id, status, error_message)
    except Exception as e:
        logger.error(f"❌ Error updating website status: {e}")
        return False


async def queue_website_for_scraping(
    url: str,
    user_role_id: int = None,
    max_depth: int = 2,
    max_pages: int = 100,
    max_concurrent: int = 10,
    delay_between_requests: float = 0.0
) -> Dict[str, Any]:
    """
    Queue website for scraping via Celery.
    Flow: create DB record → dispatch to Celery with website_id → update DB with real task_id.

    Args:
        url: Website URL to scrape
        user_role_id: User role ID (optional, for audit trail)
        max_depth: Maximum crawl depth
        max_pages: Maximum pages to crawl
        max_concurrent: Maximum concurrent requests
        delay_between_requests: Delay between requests in seconds
    """
    try:
        import uuid

        # Build options dict for the Celery task
        options = {
            'max_depth': max_depth,
            'max_pages': max_pages,
            'max_concurrent': max_concurrent,
            'delay_between_requests': delay_between_requests
        }

        # Create DB record first with a placeholder task_id so we get the website_id
        placeholder_task_id = str(uuid.uuid4())
        website_id = await create_website_record(url, user_role_id, placeholder_task_id)

        if not website_id:
            return {
                "success": False,
                "error": "Failed to create website record"
            }

        # Dispatch to Celery worker with the real website_id — Celery assigns the task ID
        logger.info(f"📤 [CELERY] Dispatching website scraping task for URL: {url}, website_id: {website_id}")
        result = web_celery.send_task(
            'tasks.scrape_website_task',
            args=[website_id, url, options],
            queue='web_crawling'
        )
        task_id = result.id

        # Update DB record with the real Celery task ID
        dao = get_webcrawl_dao()
        await dao.update_celery_task_id(website_id, task_id)

        logger.info(f"✅ Queued website scraping task: {task_id} for website ID: {website_id}")
        return {
            "success": True,
            "message": "Website scraping started successfully",
            "task_id": task_id,
            "website_id": str(website_id),
            "url": url,
            "status": "Queued"
        }

    except Exception as e:
        logger.error(f"❌ Error queuing website for scraping: {e}")
        return {
            "success": False,
            "error": str(e)
        }


async def queue_website_for_deletion(website_id: int) -> Dict[str, Any]:
    """
    Queue website for deletion if currently processing.
    """
    try:
        # Get website details first
        website_record = await get_website_by_id(website_id)
        if not website_record:
            return {
                "success": False,
                "error": "Website not found"
            }

        # Check if website is currently processing
        if website_record['processing_status'] in ('pending', 'processing'):
            # Generate task ID for deletion
            celery_task_id = str(uuid.uuid4())
            
            # Update website status to queued for deletion
            await update_website_status(website_id, 'queued_for_deletion')
            
            # Queue deletion task
            redis_queue = RedisMessageQueue()
            success = redis_queue.publish_web_task(celery_task_id=celery_task_id)
            
            if success:
                logger.info(f"✅ Queued website {website_id} for deletion")
                return {
                    "success": True,
                    "message": "Website deletion queued successfully",
                    "task_id": celery_task_id,
                    "website_id": str(website_id)
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to queue deletion task"
                }
        else:
            # Website is not processing, delete directly
            from knowledgebase_ingestion.service.file_service import FileService
            file_service = FileService()
            result = await file_service.delete_website_logic(str(website_id))
            
            return result
    except Exception as e:
        logger.error(f"❌ Error queuing website for deletion: {e}")
        return {
            "success": False,
            "error": str(e)
        }


async def get_website_details_for_worker(task_id: str) -> Optional[Dict[str, Any]]:
    """
    Get website details for worker processing using celery_task_id.
    """
    try:
        dao = get_webcrawl_dao()
        return await dao.get_website_details_by_task_id(task_id)
    except Exception as e:
        logger.error(f"❌ Error getting website details for worker: {e}")
        return None


async def validate_scraping_request(request_data: Dict[str, Any]) -> Dict[str, Any]:
    """
    Validate website scraping request and return validation result.
    """
    try:
        url = request_data.get('url')
        if not url:
            return {
                "valid": False,
                "error": "URL is required"
            }
        
        # Basic URL validation
        if not url.startswith(('http://', 'https://')):
            return {
                "valid": False,
                "error": "URL must start with http:// or https://"
            }
        
        # Extract and validate optional parameters
        max_depth = request_data.get('max_depth', 2)
        max_pages = request_data.get('max_pages', 100)
        max_concurrent = request_data.get('max_concurrent', 10)
        delay_between_requests = request_data.get('delay_between_requests', 0.0)
        
        # Validate parameter ranges
        if max_depth < 1 or max_depth > 10:
            return {
                "valid": False,
                "error": "max_depth must be between 1 and 10"
            }
        
        if max_pages < 1 or max_pages > 1000:
            return {
                "valid": False,
                "error": "max_pages must be between 1 and 1000"
            }
        
        if max_concurrent < 1 or max_concurrent > 50:
            return {
                "valid": False,
                "error": "max_concurrent must be between 1 and 50"
            }
        
        if delay_between_requests < 0.0 or delay_between_requests > 10.0:
            return {
                "valid": False,
                "error": "delay_between_requests must be between 0.0 and 10.0"
            }
        
        return {
            "valid": True,
            "url": url,
            "max_depth": max_depth,
            "max_pages": max_pages,
            "max_concurrent": max_concurrent,
            "delay_between_requests": delay_between_requests
        }
    except Exception as e:
        logger.error(f"❌ Error validating scraping request: {e}")
        return {
            "valid": False,
            "error": f"Validation error: {str(e)}"
        }
