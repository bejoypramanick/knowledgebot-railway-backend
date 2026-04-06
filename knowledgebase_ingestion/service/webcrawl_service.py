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
from shared.redis_ui_cache import invalidate_kb_caches

logger = get_otel_logger("webcrawl_service", "knowledgebase-ingestion")

# Singleton DAO instance
_webcrawl_dao = None

def get_webcrawl_dao() -> WebCrawlDAO:
    """Get singleton WebCrawlDAO instance."""
    global _webcrawl_dao
    if _webcrawl_dao is None:
        _webcrawl_dao = WebCrawlDAO()
    return _webcrawl_dao


async def create_website_record(url: str, user_role_id: str = None, task_id: str = None) -> Optional[str]:
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


async def get_website_by_id(website_id: str) -> Optional[Dict[str, Any]]:
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


async def update_website_status(website_id: str, status: str, error_message: str = None) -> bool:
    """Update website processing status."""
    try:
        dao = get_webcrawl_dao()
        res = await dao.update_website_status(website_id, status, error_message)
        if res:
            await invalidate_kb_caches()
        return res
    except Exception as e:
        logger.error(f"❌ Error updating website status: {e}")
        return False


async def queue_website_for_scraping(
    url: str,
    user_role_id: str = None,
    max_depth: int = 2,
    max_pages: int = 100,
    max_concurrent: int = 10,
    delay_between_requests: float = 0.0,
    replace_existing: bool = False,
    tenant_id: str = None,
    tenant_slug: str = None,
    user_email: str = None,
) -> Dict[str, Any]:
    """
    Queue website for scraping via Celery.
    Flow: check duplicates → create DB record → dispatch to Celery with website_id → update DB with real task_id.

    Args:
        url: Website URL to scrape
        user_role_id: User role ID (optional, for audit trail)
        max_depth: Maximum crawl depth
        max_pages: Maximum pages to crawl
        max_concurrent: Maximum concurrent requests
        delay_between_requests: Delay between requests in seconds
        replace_existing: If True, mark existing crawl as deleted and allow new crawl
    """
    logger.info("=" * 80)
    logger.info("🌐 [SCRAPE_START] Queue website for scraping - START")
    logger.info("=" * 80)
    logger.info(f"📍 [INPUT] URL: {url}")
    logger.info(f"👤 [INPUT] User Role ID: {user_role_id}")
    logger.info(f"⚙️  [INPUT] Options: max_depth={max_depth}, max_pages={max_pages}, max_concurrent={max_concurrent}, delay={delay_between_requests}")
    logger.info(f"🔄 [INPUT] Replace existing: {replace_existing}")

    try:
        import uuid
        from shared.sqlalchemy_db import get_db_session
        from sqlalchemy import text

        # Check for duplicate URL (only active crawls)
        logger.info(f"🔍 [DUPLICATE_CHECK] Checking for existing crawls of URL: {url}")
        async with get_db_session() as session:
            # Get all websites with this URL
            result = await session.execute(
                text("SELECT id, original_url, processing_status FROM scraped_websites WHERE original_url = :url ORDER BY id DESC"),
                {"url": url}
            )
            all_websites = result.mappings().all()
            logger.info(f"🔍 [DUPLICATE_CHECK_ALL] Found {len(all_websites)} total websites with URL '{url}':")
            for w in all_websites:
                logger.info(f"   - ID={w['id']}, status={w['processing_status']}")

            # Check for active crawls (exclude failed, deleted, cancelled)
            result = await session.execute(
                text("SELECT id, original_url, processing_status FROM scraped_websites WHERE original_url = :url AND processing_status IN ('pending', 'processing', 'queued', 'completed') LIMIT 1"),
                {"url": url}
            )
            existing_active = result.mappings().first()

            if existing_active:
                if replace_existing:
                    # Mark existing website as deleted
                    logger.info(f"🔄 [REPLACE] Marking existing website as deleted: ID={existing_active['id']}")
                    await session.execute(
                        text("UPDATE scraped_websites SET processing_status = 'deleted', updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
                        {"id": existing_active['id']}
                    )
                    await session.commit()
                    logger.info(f"✅ [REPLACE] Existing website marked as deleted, allowing new crawl")
                else:
                    logger.warning(f"🔍 [DUPLICATE_CHECK] Found ACTIVE crawl: ID={existing_active['id']}, url={existing_active['original_url']}, status={existing_active['processing_status']}")
                    return {
                        "success": False,
                        "error": f"Website is already being crawled or has been crawled (ID: {existing_active['id']}, Status: {existing_active['processing_status']}).",
                        "duplicate_website_id": str(existing_active['id'])
                    }
            else:
                logger.info(f"🔍 [DUPLICATE_CHECK] No active crawl found for: {url}")

        # Build options dict for the Celery task
        options = {
            'max_depth': max_depth,
            'max_pages': max_pages,
            'max_concurrent': max_concurrent,
            'delay_between_requests': delay_between_requests,
            'user_role_id': user_role_id,
            'tenant_id': tenant_id,
            'tenant_slug': tenant_slug,
            'user_email': user_email,
        }
        logger.info(f"✅ [OPTIONS] Built options dict: {options}")

        # Create DB record first with a placeholder task_id so we get the website_id
        placeholder_task_id = str(uuid.uuid4())
        logger.info(f"📝 [DB_CREATE] Creating DB record with placeholder task_id: {placeholder_task_id}")
        website_id = await create_website_record(url, user_role_id, placeholder_task_id)

        if not website_id:
            logger.error("❌ [DB_CREATE_ERROR] Failed to create website record - returned None")
            return {
                "success": False,
                "error": "Failed to create website record"
            }
        logger.info(f"✅ [DB_CREATE_SUCCESS] Website record created with ID: {website_id}")
        
        # Invalidate cache so the pending record shows up in UI
        await invalidate_kb_caches()

        # Dispatch to Celery worker with the real website_id — Celery assigns the task ID
        logger.info("=" * 80)
        logger.info(f"📤 [CELERY_DISPATCH] About to dispatch to Celery...")
        logger.info("=" * 80)
        logger.info(f"🔧 [CELERY_CONFIG] web_celery object: {web_celery}")
        logger.info(f"🔧 [CELERY_CONFIG] web_celery broker: {web_celery.conf.get('broker_url', 'NOT SET')}")
        logger.info(f"🔧 [CELERY_CONFIG] web_celery result_backend: {web_celery.conf.get('result_backend', 'NOT SET')}")
        logger.info(f"   Task: 'tasks.scrape_website_task'")
        logger.info(f"   Args: website_id={website_id}, url={url}")
        logger.info(f"   Queue: 'web_crawling'")

        try:
            logger.info(f"📬 [CELERY_SEND_CALL] Calling web_celery.send_task()...")
            result = web_celery.send_task(
                'tasks.scrape_website_task',
                args=[website_id, url, options],
                queue='web_crawling'
            )
            logger.info(f"✅ [CELERY_SEND_SUCCESS] Task dispatched successfully!")
            logger.info(f"   Result type: {type(result)}")
            logger.info(f"   Result object: {result}")
            logger.info(f"   Result.__dict__: {result.__dict__ if hasattr(result, '__dict__') else 'N/A'}")

            task_id = result.id
            logger.info(f"✅ [CELERY_TASK_ID] Celery assigned task ID: {task_id}")
            logger.info(f"   Task state: {result.state}")
            logger.info(f"   Task status: {result.status}")
        except Exception as celery_err:
            logger.error("=" * 80)
            logger.error(f"❌ [CELERY_SEND_ERROR] FAILED to dispatch to Celery")
            logger.error("=" * 80)
            logger.error(f"🚨 [ERROR_TYPE] {type(celery_err).__name__}")
            logger.error(f"🚨 [ERROR_MESSAGE] {str(celery_err)}")
            logger.error(f"🚨 [ERROR_DETAILS] Full traceback:")
            logger.error("", exc_info=True)
            raise

        # Update DB record with the real Celery task ID
        logger.info(f"💾 [DB_UPDATE] Updating DB with real Celery task ID: {task_id}")
        dao = get_webcrawl_dao()
        try:
            await dao.update_celery_task_id(website_id, task_id)
            logger.info(f"✅ [DB_UPDATE_SUCCESS] DB updated with Celery task ID")
        except Exception as db_err:
            logger.error(f"❌ [DB_UPDATE_ERROR] Failed to update DB with task ID: {db_err}", exc_info=True)
            raise

        logger.info("=" * 80)
        logger.info(f"✅ [SCRAPE_QUEUED] Website scraping task successfully queued")
        logger.info("=" * 80)
        logger.info(f"📋 [RESULT] Website ID: {website_id}")
        logger.info(f"📋 [RESULT] Celery Task ID: {task_id}")
        logger.info(f"📋 [RESULT] URL: {url}")

        # Fetch the complete website record for UI population
        try:
            full_website = await get_website_by_id(website_id)
            if full_website:
                logger.info(f"✅ [WEBSITE_FETCH] Fetched full website record for UI")
                return {
                    "success": True,
                    "message": "Website scraping started successfully",
                    "task_id": task_id,
                    "website_id": str(website_id),
                    "url": url,
                    "domain": full_website.get('domain', ''),
                    "processing_status": full_website.get('processing_status', 'pending'),
                    "char_count": full_website.get('char_count', 0),
                    "file_size": full_website.get('file_size', 0),
                    "pages_scraped": full_website.get('pages_scraped', 0),
                    "created_at": full_website.get('created_at').isoformat() if full_website.get('created_at') else None,
                    "updated_at": full_website.get('updated_at').isoformat() if full_website.get('updated_at') else None,
                    "children": [],
                    "status": "Queued"
                }
        except Exception as fetch_err:
            logger.warning(f"⚠️ Could not fetch full website record: {fetch_err}")

        # Fallback response if fetch fails
        return {
            "success": True,
            "message": "Website scraping started successfully",
            "task_id": task_id,
            "website_id": str(website_id),
            "url": url,
            "domain": url.split('/')[2] if '://' in url else url,
            "processing_status": "pending",
            "char_count": 0,
            "file_size": 0,
            "pages_scraped": 0,
            "created_at": None,
            "updated_at": None,
            "children": [],
            "status": "Queued"
        }

    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"❌ [SCRAPE_ERROR] Error queuing website for scraping")
        logger.error("=" * 80)
        logger.error(f"📍 [ERROR_INPUT] URL: {url}")
        logger.error(f"🚨 [ERROR_DETAILS] {type(e).__name__}: {str(e)}", exc_info=True)
        return {
            "success": False,
            "error": str(e)
        }


async def get_task_status(task_id: str) -> Dict[str, Any]:
    """
    Get the status of a Celery task.

    Args:
        task_id: Celery task ID

    Returns:
        Task status information
    """
    try:
        logger.info(f"🔍 [TASK_STATUS_CHECK] Checking status for task: {task_id}")

        # Get task result from Celery
        task_result = web_celery.AsyncResult(task_id)

        logger.info(f"📊 [TASK_STATE] Task state: {task_result.state}")
        logger.info(f"📊 [TASK_RESULT] Task result: {task_result.result}")
        logger.info(f"📊 [TASK_READY] Task ready: {task_result.ready()}")
        logger.info(f"📊 [TASK_SUCCESSFUL] Task successful: {task_result.successful()}")
        logger.info(f"📊 [TASK_FAILED] Task failed: {task_result.failed()}")

        return {
            "task_id": task_id,
            "state": task_result.state,
            "result": str(task_result.result) if task_result.result else None,
            "ready": task_result.ready(),
            "successful": task_result.successful(),
            "failed": task_result.failed()
        }
    except Exception as e:
        logger.error(f"❌ [TASK_STATUS_ERROR] Error checking task status: {e}", exc_info=True)
        return {
            "task_id": task_id,
            "error": str(e)
        }


async def check_redis_queue() -> Dict[str, Any]:
    """
    Check Redis queue for pending tasks.

    Returns:
        Redis queue information
    """
    try:
        logger.info("🔍 [REDIS_CHECK] Checking Redis queue...")

        import redis
        from shared.redis_factory import resolve_redis_url

        redis_url = resolve_redis_url(
            primary_env_var='web_task_queue',
            db_env_var='WEB_TASK_QUEUE_REDIS_DB',
            default_db=1,
        )
        redis_client = redis.from_url(redis_url, decode_responses=True)

        # Check queue length
        queue_length = redis_client.llen('celery')  # Default Celery queue
        web_crawling_length = redis_client.llen('web_crawling')  # Our specific queue

        logger.info(f"📊 [REDIS_QUEUES] Celery queue length: {queue_length}")
        logger.info(f"📊 [REDIS_QUEUES] web_crawling queue length: {web_crawling_length}")

        # Get queue contents (first 10 items)
        queue_items = redis_client.lrange('web_crawling', 0, 9)
        logger.info(f"📊 [REDIS_ITEMS] Queue items (first 10): {queue_items}")

        redis_client.close()

        return {
            "celery_queue_length": queue_length,
            "web_crawling_queue_length": web_crawling_length,
            "sample_items": queue_items[:3] if queue_items else []
        }
    except Exception as e:
        logger.error(f"❌ [REDIS_CHECK_ERROR] Error checking Redis queue: {e}", exc_info=True)
        return {
            "error": str(e)
        }


async def delete_website(website_id: str) -> Dict[str, Any]:
    """
    Delete website atomically with complete cleanup
    """
    from .atomic_deletion_service import atomic_deletion_service
    
    logger.info(f"🗑️ [DELETE_WEBSITE] Starting atomic website deletion for ID: {website_id}")
    
    result = await atomic_deletion_service.delete_website_atomically(website_id)
    
    if result["success"]:
        logger.info(f"✅ [DELETE_WEBSITE] Website {website_id} deleted successfully")
    else:
        logger.error(f"❌ [DELETE_WEBSITE] Failed to delete website {website_id}: {result.get('error')}")
    
    return result


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
        replace_existing = request_data.get('replace_existing', False)
        
        # Validate parameter ranges
        # max_depth=0 is allowed (scans only main page, no child links)
        if max_depth < 0 or max_depth > 10:
            return {
                "valid": False,
                "error": "max_depth must be between 0 and 10 (0 = main page only)"
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
            "delay_between_requests": delay_between_requests,
            "replace_existing": replace_existing
        }
    except Exception as e:
        logger.error(f"❌ Error validating scraping request: {e}")
        return {
            "valid": False,
            "error": f"Validation error: {str(e)}"
        }
