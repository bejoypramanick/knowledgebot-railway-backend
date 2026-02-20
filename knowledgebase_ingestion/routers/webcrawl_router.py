"""
Web Crawl Router
Handles all website scraping related endpoints
"""
import os
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from typing import Dict, Any

from knowledgebase_ingestion.utils.auth import extract_user_from_request
from knowledgebase_ingestion.utils.logging import get_otel_logger
from knowledgebase_ingestion.service.webcrawl_service import (
    get_webcrawl_dao, get_pending_websites, get_website_by_id,
    cancel_websites, update_website_status, queue_website_for_scraping,
    queue_website_for_deletion, validate_scraping_request, get_task_status, check_redis_queue
)
from shared.redis_message_queue import RedisMessageQueue
from shared.celery_dispatcher import web_celery

logger = get_otel_logger("webcrawl_router", "knowledgebase-ingestion")

# NOTE: Prefix is provided by include_router() in main.py
# Do NOT include full path here to avoid double prefix (prefix=/api/v1/knowledgebase in include_router)
router = APIRouter(tags=["web-crawl"])

# =================================
# WEBSITE STATUS ENDPOINTS
# =================================

@router.get("/status")
async def get_web_processing_status(request: Request = None):
    """Get processing status for all pending/processing websites"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Get all websites with their current status
        websites = await get_pending_websites()

        return {
            "success": True,
            "websites": [
                {
                    "id": str(w['id']),
                    "type": "website",
                    "name": w['original_url'],
                    "processing_status": w['processing_status'],
                    "error_message": w['error_message'],
                    "created_at": w['created_at'].isoformat() if w['created_at'] else None,
                    "updated_at": w['updated_at'].isoformat() if w['updated_at'] else None
                }
                for w in websites
            ]
        }
    except Exception as e:
        logger.error(f"Error getting website processing status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{item_id}")
async def get_web_item_processing_status(item_id: str, request: Request = None):
    """Get processing status for a single website"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Get website record
        website_record = await get_website_by_id(int(item_id))
        if website_record:
            return {
                "success": True,
                "type": "website",
                "id": str(website_record['id']),
                "name": website_record['original_url'],
                "processing_status": website_record['processing_status'],
                "error_message": website_record['error_message'],
                "created_at": website_record['created_at'].isoformat() if website_record['created_at'] else None,
                "updated_at": website_record['updated_at'].isoformat() if website_record['updated_at'] else None
            }

        raise HTTPException(status_code=404, detail=f"Website {item_id} not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting website item processing status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# TASK CANCELLATION ENDPOINTS
# =================================

@router.post("/cancel/{item_id}")
async def cancel_web_task(item_id: str, request: Request = None):
    """
    Cancel a pending or processing website task.
    Sets Redis cancellation flag and marks as cancelled in database.
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Revoke queued Celery task (stops it before it starts)
        web_celery.control.revoke(item_id, terminate=False)
        logger.info(f"✅ Revoked Celery task {item_id} from queue")

        # Set Redis cancellation flag for in-progress tasks
        redis_queue = RedisMessageQueue()
        success = redis_queue.set_task_cancelled(item_id)

        if success:
            logger.info(f"✅ Set cancellation flag for website task {item_id}")

            # Update database status to cancelled
            websites_cancelled = await cancel_websites()

            if websites_cancelled > 0:
                logger.info(f"✅ Marked {websites_cancelled} website tasks as cancelled in database")
            else:
                logger.warning(f"⚠️ Website task {item_id} not found or already completed")
        else:
            logger.error(f"❌ Failed to set cancellation flag for website task {item_id}")

        return {
            "success": success,
            "message": "Website task cancellation requested" if success else "Failed to cancel website task",
            "item_id": item_id
        }
        
    except Exception as e:
        logger.error(f"Error cancelling website task {item_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel-all")
async def cancel_all_web_tasks(request: Request = None):
    """
    Cancel all pending and processing website tasks.
    Sets Redis cancellation flags and marks as cancelled in database.
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Purge all queued Celery tasks (prevents pending tasks from being picked up)
        web_celery.control.purge()
        logger.info("✅ Purged Celery web_crawling queue")

        # Also clear any legacy Redis queue keys
        redis_queue = RedisMessageQueue()
        redis_queue.clear_web_task_queue()
        logger.info("✅ Cleared web task queue in Redis")

        # Mark all pending/processing tasks as cancelled in database
        websites_cancelled = await cancel_websites()

        if websites_cancelled > 0:
            logger.info(f"✅ Marked {websites_cancelled} website tasks as cancelled in database")

        return {
            "success": True,
            "message": f"Cancelled {websites_cancelled} website tasks",
            "cancelled_count": websites_cancelled
        }

    except Exception as e:
        logger.error(f"Error cancelling all website tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# DELETE ENDPOINTS
# =================================

@router.delete("/web/{website_id}")
async def delete_web_item(website_id: str, request: Request = None):
    """
    Delete a website with transactional safety.
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Queue website for deletion (handles both processing and direct deletion)
        result = await queue_website_for_deletion(int(website_id))
        
        if result.get('success'):
            logger.info(f"✅ Website deletion processed: {website_id}")
            return result
        else:
            raise HTTPException(status_code=500, detail=result.get('error', 'Deletion failed'))
                    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting website {website_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# WEBSITE SCRAPING ENDPOINTS
# =================================

@router.post("/webcrawl/async")
async def scrape_website_async_endpoint(request: Request = None):
    """
    Async website scraping endpoint with Redis task queue - returns immediately with Queued status.
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        logger.info(f"🔐 [AUTH] User Email: {user_email}, User ID (from header): {user_id}")
        
        # Look up user_role_id from database using email
        from knowledgebase_ingestion.utils.auth import get_user_role_id_from_email
        user_role_id = await get_user_role_id_from_email(user_email)
        logger.info(f"🔐 [AUTH] User Role ID (from DB): {user_role_id}")

        # Get request data
        request_data = await request.json()

        # Validate request
        validation_result = await validate_scraping_request(request_data)
        if not validation_result['valid']:
            raise HTTPException(status_code=400, detail=validation_result['error'])

        # Queue website for scraping with all validated params
        result = await queue_website_for_scraping(
            url=validation_result['url'],
            user_role_id=user_role_id,  # Use user_role_id from database, not user_id from header
            max_depth=validation_result.get('max_depth', 2),
            max_pages=validation_result.get('max_pages', 100),
            max_concurrent=validation_result.get('max_concurrent', 10),
            delay_between_requests=validation_result.get('delay_between_requests', 0.0),
            replace_existing=validation_result.get('replace_existing', False)
        )
        
        if result.get('success'):
            logger.info(f"✅ Website scraping queued: {result.get('task_id')}")
            return result
        else:
            raise HTTPException(status_code=500, detail=result.get('error', 'Failed to queue scraping'))
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in async website scraping: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# DEBUG/MONITORING ENDPOINTS
# =================================

@router.get("/debug/task-status/{task_id}")
async def debug_task_status(task_id: str, request: Request = None):
    """DEBUG: Check status of a Celery task"""
    try:
        extract_user_from_request(request)  # Verify auth
        status = await get_task_status(task_id)
        return {
            "success": True,
            "task_status": status
        }
    except Exception as e:
        logger.error(f"Error getting task status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debug/redis-queue")
async def debug_redis_queue(request: Request = None):
    """DEBUG: Check Redis queue status"""
    try:
        extract_user_from_request(request)  # Verify auth
        queue_info = await check_redis_queue()
        return {
            "success": True,
            "redis_queue_info": queue_info
        }
    except Exception as e:
        logger.error(f"Error checking Redis queue: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/debug/celery-test")
async def debug_celery_test(request: Request = None):
    """DEBUG: Test if Celery can dispatch a task"""
    try:
        extract_user_from_request(request)  # Verify auth

        logger.info("=" * 80)
        logger.info("🧪 [CELERY_TEST] Testing Celery dispatcher...")
        logger.info("=" * 80)

        # Try to dispatch a test task
        logger.info("📤 [CELERY_TEST] Dispatching test debug_task...")
        try:
            result = web_celery.send_task('celery_app.debug_task', queue='web_crawling')
            logger.info(f"✅ [CELERY_TEST] Task dispatched successfully!")
            logger.info(f"   Task ID: {result.id}")
            logger.info(f"   Result type: {type(result)}")

            return {
                "success": True,
                "message": "Celery dispatcher test successful",
                "task_id": result.id,
                "broker_url": os.getenv('WEB_REDIS_URL', os.getenv('REDIS_URL', 'Not set')).split('@')[-1] if os.getenv('WEB_REDIS_URL') or os.getenv('REDIS_URL') else 'Not set'
            }
        except Exception as celery_err:
            logger.error(f"❌ [CELERY_TEST] Celery dispatch failed: {celery_err}", exc_info=True)
            return {
                "success": False,
                "error": str(celery_err),
                "broker_url": os.getenv('WEB_REDIS_URL', os.getenv('REDIS_URL', 'Not set')).split('@')[-1] if os.getenv('WEB_REDIS_URL') or os.getenv('REDIS_URL') else 'Not set'
            }
    except Exception as e:
        logger.error(f"Error in Celery test: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# HEALTH ENDPOINTS
# =================================

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "web-crawl",
        "timestamp": "2025-01-19T00:00:00Z"
    }
