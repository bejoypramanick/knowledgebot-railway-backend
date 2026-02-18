"""
File Upload Router
Handles all file upload related endpoints
"""
import uuid
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
from shared.redis_message_queue import RedisMessageQueue

logger = get_otel_logger("fileupload_router", "knowledgebase-ingestion")

router = APIRouter(prefix="/api/v1/gateway/knowledgebase", tags=["file-upload"])

# =================================
# FILE LISTING ENDPOINTS
# =================================

@router.get("/files")
async def get_all_files(request: Request = None):
    """Get all files and websites with their current status"""
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
        
        # Initialize Redis message queue
        redis_queue = RedisMessageQueue()
        
        # Set cancellation flag in Redis
        cancellation_key = f"task_cancelled:{item_id}"
        success = redis_queue._connection.set(cancellation_key, "1", ex=3600)  # 1 hour expiry
        
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
        
        # Initialize Redis message queue
        redis_queue = RedisMessageQueue()
        
        # Get all pending/processing tasks
        cancelled_count = 0
        files_cancelled = await cancel_files()
        
        if files_cancelled > 0:
            logger.info(f"✅ Marked {files_cancelled} file tasks as cancelled in database")
            
        return {
            "success": files_cancelled > 0,
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

            # Generate task ID locally
            celery_task_id = str(uuid.uuid4())

            # Create file record in database
            record_data = {
                'user_id': user_id,
                'original_filename': validation_result['original_filename'],
                'file_display_name': file_display_name or validation_result['filename'],
                'size_bytes': file_size,
                'mime_type': validation_result['mime_type'],
                'processing_status': 'pending',
                'source': 'upload',
                'sha256_hash': await calculate_file_hash(file_bytes),
                's3_key': s3_key
            }

            from knowledgebase_ingestion.service.fileupload_service import create_file_record
            file_id = await create_file_record(record_data)

            if not file_id:
                raise HTTPException(status_code=500, detail="Failed to create file record")

            # Dispatch to worker via Redis message queue
            logger.info(f"📤 [REDIS] Queuing file task: {celery_task_id}")
            redis_queue = RedisMessageQueue()
            success = redis_queue.publish_file_task(celery_task_id=celery_task_id)

            if not success:
                logger.error(f"❌ Failed to queue file task to Redis")
                raise HTTPException(status_code=500, detail="Failed to queue file processing task")

            logger.info(f"✅ File task queued to Redis: {celery_task_id}")

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
