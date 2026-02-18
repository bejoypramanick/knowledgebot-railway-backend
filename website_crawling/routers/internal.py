"""
Internal API endpoints for service-to-service communication
These endpoints are only accessible by other Railway services
"""
from fastapi import APIRouter, HTTPException
from website_crawling.celery_app import celery_app
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("internal_router", "website-crawling")
router = APIRouter(prefix="/internal", tags=["internal"])

@router.post("/celery/purge")
async def purge_celery_queue():
    """Purge all pending tasks from the Celery queue"""
    try:
        celery_app.control.purge()
        logger.info("✅ Purged website crawling Celery queue")
        return {"success": True, "message": "Website crawling queue purged successfully"}
    except Exception as e:
        logger.error(f"❌ Failed to purge Celery queue: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to purge queue: {e}")

@router.post("/celery/revoke/{task_id}")
async def revoke_celery_task(task_id: str):
    """Revoke a specific Celery task"""
    try:
        celery_app.control.revoke(task_id, terminate=True)
        logger.info(f"✅ Revoked Celery task: {task_id}")
        return {"success": True, "message": f"Task {task_id} revoked successfully"}
    except Exception as e:
        logger.error(f"❌ Failed to revoke task {task_id}: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to revoke task: {e}")

@router.post("/cancel-all")
async def cancel_all_tasks():
    """Cancel all tasks and mark them as cancelled in database"""
    try:
        from shared.db import get_db_connection
        
        # Mark all pending/processing tasks as cancelled
        async with get_db_connection() as conn:
            await conn.execute(
                "UPDATE scraped_websites SET processing_status = 'cancelled' WHERE processing_status IN ('pending', 'processing')"
            )
        
        # Purge the queue
        celery_app.control.purge()
        
        logger.info("✅ Cancelled all website crawling tasks")
        return {"success": True, "message": "All tasks cancelled successfully"}
    except Exception as e:
        logger.error(f"❌ Failed to cancel all tasks: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel all tasks: {e}")
