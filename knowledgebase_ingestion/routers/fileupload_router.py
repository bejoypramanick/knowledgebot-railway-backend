"""
File Upload Router
Handles all file upload related endpoints
"""
from fastapi import APIRouter, HTTPException, Request, UploadFile, Form
from fastapi.responses import JSONResponse
from typing import Optional, Dict, Any

from knowledgebase_ingestion.utils.auth import extract_user_from_request
from knowledgebase_ingestion.utils.logging import get_otel_logger
from knowledgebase_ingestion.service.fileupload_service import (
    get_fileupload_dao, get_pending_files, get_file_by_id,
    cancel_files, update_file_status, queue_file_for_deletion,
    validate_file_upload
)
from knowledgebase_ingestion.service.file_service import get_file_service
from knowledgebase_ingestion.dao.webcrawl_dao import WebCrawlDAO
from shared.redis_message_queue import RedisMessageQueue
from shared.celery_dispatcher import file_celery

logger = get_otel_logger("fileupload_router", "knowledgebase-ingestion")

router = APIRouter(prefix="/api/v1/gateway/knowledgebase", tags=["file-upload"])

# =================================
# FILE LISTING ENDPOINTS
# =================================

@router.get("/files")
async def get_all_files(request: Request = None):
    """Get all files and websites with their current status and hierarchical structure"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)

        # Get all uploaded files with their current status
        files = await get_pending_files()

        # Get all hierarchical websites (NEW)
        webcrawl_dao = WebCrawlDAO()
        websites = await webcrawl_dao.get_hierarchical_websites()

        # Format files for response
        files_list = [
            {
                "id": str(f['id']),
                "type": "file",
                "name": f['original_filename'],
                "processing_status": f['processing_status'],
                "error_message": f['error_message'],
                "created_at": f['created_at'].isoformat() if f['created_at'] else None,
                "updated_at": f['updated_at'].isoformat() if f['updated_at'] else None
            }
            for f in files
        ]

        return {
            "success": True,
            "files": files_list,
            "websites": websites,  # NEW: hierarchical website tree
            "count": len(files_list),
            "sources": {
                "upload": len(files_list),
                "scrape": len(websites)  # Count of root-level websites
            }
        }
    except Exception as e:
        logger.error(f"Error getting files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status")
async def get_file_processing_status(request: Request = None):
    """Get processing status for all pending/processing files"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Get all files with their current status
        files = await get_pending_files()

        return {
            "success": True,
            "files": [
                {
                    "id": str(f['id']),
                    "type": "file",
                    "name": f['original_filename'],
                    "processing_status": f['processing_status'],
                    "error_message": f['error_message'],
                    "created_at": f['created_at'].isoformat() if f['created_at'] else None,
                    "updated_at": f['updated_at'].isoformat() if f['updated_at'] else None
                }
                for f in files
            ]
        }
    except Exception as e:
        logger.error(f"Error getting file processing status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{item_id}")
async def get_file_item_processing_status(item_id: str, request: Request = None):
    """Get processing status for a single file"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Get file record
        file_record = await get_file_by_id(int(item_id))
        if file_record:
            return {
                "success": True,
                "type": "file",
                "id": str(file_record['id']),
                "name": file_record['original_filename'],
                "processing_status": file_record['processing_status'],
                "error_message": file_record['error_message'],
                "created_at": file_record['created_at'].isoformat() if file_record['created_at'] else None,
                "updated_at": file_record['updated_at'].isoformat() if file_record['updated_at'] else None
            }

        raise HTTPException(status_code=404, detail=f"File {item_id} not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting file item processing status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# TASK CANCELLATION ENDPOINTS
# =================================

@router.post("/cancel/{item_id}")
async def cancel_file_task(item_id: str, request: Request = None):
    """
    Cancel a pending or processing file task.
    Sets Redis cancellation flag and marks as cancelled in database.
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Revoke queued Celery task (stops it before it starts)
        file_celery.control.revoke(item_id, terminate=False)
        logger.info(f"✅ Revoked Celery task {item_id} from queue")

        # Set Redis cancellation flag for in-progress tasks
        redis_queue = RedisMessageQueue()
        success = redis_queue.set_task_cancelled(item_id)

        if success:
            logger.info(f"✅ Set cancellation flag for file task {item_id}")

            # Update database status to cancelled
            files_cancelled = await cancel_files()

            if files_cancelled > 0:
                logger.info(f"✅ Marked {files_cancelled} file tasks as cancelled in database")
            else:
                logger.warning(f"⚠️ File task {item_id} not found or already completed")
        else:
            logger.error(f"❌ Failed to set cancellation flag for file task {item_id}")

        return {
            "success": success,
            "message": "File task cancellation requested" if success else "Failed to cancel file task",
            "item_id": item_id
        }
        
    except Exception as e:
        logger.error(f"Error cancelling file task {item_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel-all")
async def cancel_all_file_tasks(request: Request = None):
    """
    Cancel all pending and processing file tasks.
    Sets Redis cancellation flags and marks as cancelled in database.
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Purge all queued Celery tasks (prevents pending tasks from being picked up)
        file_celery.control.purge()
        logger.info("✅ Purged Celery file_processing queue")

        # Also clear any legacy Redis queue keys
        redis_queue = RedisMessageQueue()
        redis_queue.clear_file_task_queue()
        logger.info("✅ Cleared file task queue in Redis")

        # Mark all pending/processing tasks as cancelled in database
        files_cancelled = await cancel_files()

        if files_cancelled > 0:
            logger.info(f"✅ Marked {files_cancelled} file tasks as cancelled in database")

        return {
            "success": True,
            "message": f"Cancelled {files_cancelled} file tasks",
            "cancelled_count": files_cancelled
        }

    except Exception as e:
        logger.error(f"Error cancelling all file tasks: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# DELETE ENDPOINTS
# =================================

@router.delete("/files/{file_id}")
async def delete_file(file_id: str, request: Request = None):
    """
    Delete an uploaded file with transactional safety.
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Queue file for deletion (handles both processing and direct deletion)
        result = await queue_file_for_deletion(int(file_id))
        
        if result.get('success'):
            logger.info(f"✅ File deletion processed: {file_id}")
            return result
        else:
            raise HTTPException(status_code=500, detail=result.get('error', 'Deletion failed'))
                    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting file {file_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# FILE UPLOAD ENDPOINTS
# =================================

@router.post("/upload/async")
async def upload_file_async(
    file: UploadFile = Form(...),
    file_display_name: Optional[str] = Form(None),
    request: Request = None
):
    """
    Async file upload endpoint with Redis task queue - returns immediately with pending status.
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Validate file
        validation_result = await validate_file_upload(file, await get_file_size(file))
        if not validation_result['valid']:
            raise HTTPException(status_code=400, detail=validation_result['error'])

        # Read file into bytes and upload to S3, then dispatch to worker
        try:
            file_bytes = await file.read()
            file_size = len(file_bytes)

            # Upload to S3
            logger.info(f"☁️ [S3] Uploading file {validation_result['filename']} ({file_size} bytes) to S3")
            from shared.s3_file_storage import s3_file_storage

            success, s3_result = await s3_file_storage.upload_file(
                file_data=file_bytes,
                original_filename=validation_result['filename'],
                file_type="upload"
            )

            if not success:
                logger.error(f"❌ S3 upload failed: {s3_result}")
                raise HTTPException(status_code=500, detail=f"File upload to S3 failed: {s3_result}")

            s3_key = s3_result
            logger.info(f"✅ [S3] File uploaded successfully: {s3_key}")

            # Dispatch to Celery worker — Celery assigns the task ID
            logger.info(f"📤 [CELERY] Dispatching file task to Celery")
            result = file_celery.send_task(
                'tasks.process_file_upload_task',
                args=[
                    validation_result['original_filename'],
                    file_display_name or validation_result['filename'],
                    s3_key,
                    file_size,
                    user_email
                ],
                queue='file_processing'
            )
            celery_task_id = result.id

            logger.info(f"✅ File task dispatched to Celery: {celery_task_id}")

            # Create file record in database with the Celery task ID
            record_data = {
                'user_id': user_id,
                'original_filename': validation_result['original_filename'],
                'file_display_name': file_display_name or validation_result['filename'],
                'size_bytes': file_size,
                'mime_type': validation_result['mime_type'],
                'processing_status': 'pending',
                'source': 'upload',
                'sha256_hash': await calculate_file_hash(file_bytes),
                's3_key': s3_key,
                'celery_task_id': celery_task_id
            }

            from knowledgebase_ingestion.service.fileupload_service import create_file_record
            file_id = await create_file_record(record_data)

            if not file_id:
                raise HTTPException(status_code=500, detail="Failed to create file record")

            return {
                "success": True,
                "message": "File processing task queued successfully",
                "task_id": celery_task_id,
                "file_id": file_id,
                "status": "Queued"
            }

        except HTTPException:
            raise
        except Exception as e:
            logger.error(f"❌ Error queuing file task: {e}")
            raise HTTPException(status_code=500, detail=str(e))

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error in async file upload: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# HEALTH ENDPOINTS
# =================================

@router.get("/health")
async def health_check():
    """Health check endpoint"""
    return {
        "status": "healthy",
        "service": "file-upload",
        "timestamp": "2025-01-19T00:00:00Z"
    }


# Helper functions
async def get_file_size(file: UploadFile) -> int:
    """Get file size from UploadFile object."""
    try:
        # Reset file position and read size
        await file.seek(0)
        content = await file.read()
        await file.seek(0)
        return len(content)
    except Exception as e:
        logger.error(f"Error getting file size: {e}")
        return 0


async def calculate_file_hash(file_bytes: bytes) -> str:
    """Calculate SHA256 hash of file bytes."""
    import hashlib
    return hashlib.sha256(file_bytes).hexdigest()
