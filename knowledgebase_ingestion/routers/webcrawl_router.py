"""
Web Crawl Router
Handles all website scraping related endpoints
"""
from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import JSONResponse
from typing import Dict, Any

from knowledgebase_ingestion.utils.auth import extract_user_from_request
from knowledgebase_ingestion.utils.logging import get_otel_logger
from knowledgebase_ingestion.service.webcrawl_service import (
    get_webcrawl_dao, get_pending_websites, get_website_by_id, 
    cancel_websites, update_website_status, queue_website_for_scraping,
    queue_website_for_deletion, validate_scraping_request
)
from shared.redis_message_queue import RedisMessageQueue

logger = get_otel_logger("webcrawl_router", "knowledgebase-ingestion")

router = APIRouter(prefix="/api/v1/gateway/knowledgebase", tags=["web-crawl"])

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
        
        # Initialize Redis message queue
        redis_queue = RedisMessageQueue()
        
        # Set cancellation flag in Redis
        cancellation_key = f"task_cancelled:{item_id}"
        success = redis_queue._connection.set(cancellation_key, "1", ex=3600)  # 1 hour expiry
        
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
        
        # Initialize Redis message queue
        redis_queue = RedisMessageQueue()
        
        # Get all pending/processing tasks
        cancelled_count = 0
        websites_cancelled = await cancel_websites()
        
        if websites_cancelled > 0:
            logger.info(f"✅ Marked {websites_cancelled} website tasks as cancelled in database")
            
        return {
            "success": websites_cancelled > 0,
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
        logger.error(f"Error deleting website {website_id}: {e}", exc_info=True)
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
        
        # Get request data
        request_data = await request.json()
        
        # Validate request
        validation_result = await validate_scraping_request(request_data)
        if not validation_result['valid']:
            raise HTTPException(status_code=400, detail=validation_result['error'])
        
        # Queue website for scraping
        result = await queue_website_for_scraping(
            validation_result['url'], 
            user_email
        )
        
        if result.get('success'):
            logger.info(f"✅ Website scraping queued: {result.get('task_id')}")
            return result
        else:
            raise HTTPException(status_code=500, detail=result.get('error', 'Failed to queue scraping'))
                
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in async website scraping: {e}", exc_info=True)
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
