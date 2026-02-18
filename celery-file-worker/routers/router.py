"""
Internal API endpoints for file worker service
These endpoints are only accessible by other Railway services
"""
import os
from fastapi import APIRouter, HTTPException
from ..celery_app import celery_app
from shared.otel_logger import get_otel_logger
from ..service.file_service import FileService
logger = get_otel_logger("internal_router", "celery-file-worker")
router = APIRouter(prefix="/internal", tags=["internal"])

@router.post("/dispatch-file")
async def dispatch_file_task(**kwargs):
    """
    Dispatch a file processing task with S3 file reference.
    Worker will download from S3, create DB record, process, and cleanup.
    """
    try:
        from tasks import process_file_upload_task

        # Extract parameters
        original_filename = kwargs.get('original_filename')
        file_display_name = kwargs.get('file_display_name')
        s3_key = kwargs.get('s3_key')  # S3 object key instead of base64 bytes
        file_size = kwargs.get('file_size')
        user_email = kwargs.get('user_email', 'admin')

        if not all([original_filename, s3_key, file_size]):
            raise HTTPException(status_code=400, detail="Missing required parameters (original_filename, s3_key, file_size)")

        logger.info(f"📋 Dispatching file task: {original_filename}")
        logger.info(f"   S3 Key: {s3_key}")
        logger.info(f"   Size: {file_size} bytes")

        # Dispatch Celery task with S3 key
        # Task will handle: download from S3, validation, DB record creation, processing, cleanup
        try:
            task = process_file_upload_task.delay(
                original_filename=original_filename,
                file_display_name=file_display_name,
                s3_key=s3_key,
                file_size=file_size,
                user_email=user_email
            )
            logger.info(f"✅ Dispatched file task: {task.id}")
            return {
                "success": True,
                "task_id": task.id,
                "message": f"File task dispatched successfully: {task.id}"
            }
        except Exception as e:
            logger.error(f"❌ Failed to queue Celery task: {e}")
            raise HTTPException(status_code=500, detail=f"Failed to queue task: {e}")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Failed to dispatch file task: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to dispatch file task: {e}")

@router.post("/celery/purge")
async def purge_celery_queue():
    """Purge all pending tasks from Celery queue"""
    try:
        celery_app.control.purge()
        logger.info("✅ Purged file processing Celery queue")
        return {"success": True, "message": "File processing queue purged successfully"}
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
        raise HTTPException(status_code=500, detail=f"Failed to revoke task: {task_id}")

@router.post("/cancel-all")
async def cancel_all_tasks():
    """Cancel all tasks and mark them as cancelled in database"""
    try:
        from shared.db import get_db_connection
        
        # Mark all pending/processing tasks as cancelled
        async with get_db_connection() as conn:
            await conn.execute(
                "UPDATE file_uploads SET processing_status = 'cancelled' WHERE processing_status IN ('pending', 'processing')"
            )
        
        # Purge queue
        celery_app.control.purge()
        
        logger.info("✅ Cancelled all file processing tasks")
        return {"success": True, "message": "All tasks cancelled successfully"}
    except Exception as e:
        logger.error(f"❌ Failed to cancel all tasks: {e}")
        raise HTTPException(status_code=500, detail=f"Failed to cancel all tasks: {e}")

@router.get("/status")
async def worker_status():
    """Worker status endpoint for health checks"""
    try:
        from celery_app import celery_app
        inspect = celery_app.control.inspect()
        stats = inspect.stats()
        active = inspect.active()
        
        return {
            "status": "healthy",
            "service": "celery-file-worker",
            "stats": stats,
            "active_tasks": len(active) if active else 0
        }
    except Exception as e:
        logger.error(f"❌ Error getting worker status: {e}")
        return {
            "status": "unhealthy",
            "service": "celery-file-worker",
            "error": str(e)
        }

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {"status": "healthy", "service": "celery-file-worker"}
