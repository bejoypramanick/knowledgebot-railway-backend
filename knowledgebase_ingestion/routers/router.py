"""Knowledgebase Ingestion Service Router

Handles file uploads, website scraping, and status queries.
Provides endpoints for UI to interact with knowledgebase operations.
"""

from fastapi import APIRouter, HTTPException, Request, UploadFile, Form
from fastapi.responses import JSONResponse, StreamingResponse
from typing import Optional, Dict, Any
import asyncio
import json
import uuid
import logging
from datetime import datetime

from ..service.file_service import FileService
from ..service.ingestion_service import IngestionService
from ..utils.auth import extract_user_from_request
from ..utils.logging import get_otel_logger
from shared.redis_message_queue import RedisMessageQueue

logger = get_otel_logger("router", "knowledgebase_ingestion")

router = APIRouter(prefix="/api/v1/gateway/knowledgebase", tags=["knowledgebase"])

# =================================
# FILE LISTING ENDPOINTS
# =================================

@router.get("/files")
async def list_files(request: Request = None):
    """List all files and websites in hierarchical structure (backward compatible)"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        knowledgebase = await file_service.get_all_knowledgebase()
        
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
                for f in knowledgebase["files"]
            ],
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
                for w in knowledgebase["websites"]
            ],
            "summary": knowledgebase["summary"],  # Add summary info
            "user": {
                "email": user_email,
                "id": user_id
            }
        }
    except Exception as e:
        logger.error(f"Error listing files: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/upload/async")
async def upload_file_async_endpoint(
    file: UploadFile = File(...),
    request: Request = None,
    display_name: Optional[str] = Form(None)
):
    """
    Async file upload endpoint with Celery - returns immediately with pending status.
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Use ingestion service for the complete flow
        ingestion_service = IngestionService()
        result = await ingestion_service.upload_file_async(
            file=file,
            user_email=user_email,
            user_id=user_id,
            display_name=display_name
        )
        
        return JSONResponse(content=result, status_code=200)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error in async file upload: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# STATUS ENDPOINTS
# =================================

@router.get("/status")
async def get_processing_status(request: Request = None):
    """Get processing status for all pending/processing items (files and websites)"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Get all files and websites with their current status
        from ..service.ingestion_service import get_pending_files, get_pending_websites
        
        files = await get_pending_files()
        websites = await get_pending_websites()

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
            ],
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
        logger.error(f"Error getting processing status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/status/{item_id}")
async def get_item_processing_status(item_id: str, request: Request = None):
    """Get processing status for a single file or website"""
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        from ..service.ingestion_service import get_file_by_id, get_website_by_id
        
        # Try file_uploads first
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

        # Try scraped_websites
        website_record = await file_dao.get_website_by_id(int(item_id))
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

        raise HTTPException(status_code=404, detail=f"Item {item_id} not found")

    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting item processing status: {e}")
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# TASK CANCELLATION ENDPOINTS
# =================================

@router.post("/cancel/{item_id}")
async def cancel_task(item_id: str, request: Request = None):
    """
    Cancel a pending or processing file/website task.
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
            logger.info(f"✅ Set cancellation flag for task {item_id}")
            
            # Update database status to cancelled
            from ..service.ingestion_service import cancel_files, cancel_websites
            
            # Try file_uploads first
            files_cancelled = await cancel_files()
            # Try scraped_websites
            websites_cancelled = await cancel_websites()
            
            total_cancelled = files_cancelled + websites_cancelled
            if total_cancelled > 0:
                logger.info(f"✅ Marked {total_cancelled} tasks as cancelled in database")
            else:
                logger.warning(f"⚠️ Task {item_id} not found or already completed")
        else:
            logger.error(f"❌ Failed to set cancellation flag for task {item_id}")
            
        return {
            "success": success,
            "message": "Task cancellation requested" if success else "Failed to cancel task",
            "item_id": item_id
        }
        
    except Exception as e:
        logger.error(f"Error cancelling task {item_id}: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/cancel-all")
async def cancel_all_tasks(request: Request = None):
    """
    Cancel all pending and processing tasks (files and websites).
    Sets Redis cancellation flags and marks as cancelled in database.
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Initialize Redis message queue
        redis_queue = RedisMessageQueue()
        
        # Get all pending/processing tasks
        from ..service.ingestion_service import cancel_files, cancel_websites
        
        # Set cancellation flags for all tasks
        cancelled_count = 0
        files_cancelled = await cancel_files()
        websites_cancelled = await cancel_websites()
        total_cancelled = files_cancelled + websites_cancelled
        
        if total_cancelled > 0:
            logger.info(f"✅ Marked {total_cancelled} tasks as cancelled in database")
            
        return {
            "success": total_cancelled > 0,
            "message": f"Cancelled {total_cancelled} tasks",
            "cancelled_count": total_cancelled
        }
        
    except Exception as e:
        logger.error(f"Error cancelling all tasks: {e}")
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
        
        # Initialize Redis message queue for task dispatch
        redis_queue = RedisMessageQueue()
        
        # Get file details first
        from ..service.ingestion_service import get_file_by_id, update_file_status
        
        file_record = await get_file_by_id(int(file_id))
        if not file_record:
            raise HTTPException(status_code=404, detail="File not found")

        # Check if file is currently processing
        if file_record['processing_status'] in ('pending', 'processing'):
            # Generate task ID for deletion
            celery_task_id = str(uuid.uuid4())
            
            # Update file status to queued for deletion
            await update_file_status(int(file_id), 'queued_for_deletion')
            
            # Queue deletion task
            success = redis_queue.publish_file_task(celery_task_id=celery_task_id)
            
            if success:
                logger.info(f"✅ Queued file {file_id} for deletion")
                return {
                    "success": True,
                    "message": "File deletion queued successfully",
                    "task_id": celery_task_id,
                    "file_id": file_id
                }
            else:
                raise HTTPException(status_code=500, detail="Failed to queue deletion task")
        else:
            # File is not processing, delete directly
            result = await file_service.delete_file_logic(file_id)
            
            if result['success']:
                logger.info(f"✅ Deleted file {file_id} directly")
                return {
                    "success": True,
                    "message": "File deleted successfully",
                    "file_id": file_id
                }
            else:
                raise HTTPException(status_code=500, detail=result.get('error', 'Deletion failed'))
                    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting file {file_id}: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.delete("/web/{website_id}")
async def delete_web_item(website_id: str, request: Request = None):
    """
    Delete a website or sitemap and all its child pages with cascade delete.
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Initialize Redis message queue for task dispatch
        redis_queue = RedisMessageQueue()
        
        # Get website details first
        from ..service.ingestion_service import get_website_by_id, update_website_status
        
        website_record = await get_website_by_id(int(website_id))
        if not website_record:
            raise HTTPException(status_code=404, detail="Website not found")

        # Check if website is currently processing
        if website_record['processing_status'] in ('pending', 'processing'):
            # Generate task ID for deletion
            celery_task_id = str(uuid.uuid4())
            
            # Update website status to queued for deletion
            await update_website_status(int(website_id), 'queued_for_deletion')
            
            # Queue deletion task
            success = redis_queue.publish_web_task(celery_task_id=celery_task_id)
            
            if success:
                logger.info(f"✅ Queued website {website_id} for deletion")
                return {
                    "success": True,
                    "message": "Website deletion queued successfully",
                    "task_id": celery_task_id,
                    "website_id": website_id
                }
            else:
                raise HTTPException(status_code=500, detail="Failed to queue deletion task")
        else:
            # Website is not processing, delete directly
            result = await file_service.delete_website_logic(website_id)
            
            if result['success']:
                logger.info(f"✅ Deleted website {website_id} directly")
                return {
                    "success": True,
                    "message": "Website deleted successfully",
                    "website_id": website_id
                }
            else:
                raise HTTPException(status_code=500, detail=result.get('error', 'Deletion failed'))
                    
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error deleting website/sitemap: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


# =================================
# WEBSITE SCRAPING ENDPOINTS
# =================================

@router.post("/webcrawl/async")
async def scrape_website_async_endpoint(request: Request = None):
    """
    Async website scraping endpoint with Celery - returns immediately with pending status.
    """
    try:
        # Extract authenticated user information
        user_email, user_id = extract_user_from_request(request)
        
        # Initialize Redis message queue
        redis_queue = RedisMessageQueue()
        
        # Get request data
        request_data = await request.json()
        
        # Validate required fields
        url = request_data.get('url')
        if not url:
            raise HTTPException(status_code=400, detail="URL is required")
        
        # Generate task ID
        task_id = str(uuid.uuid4())
        
        # Create website record with pending status
        from ..service.ingestion_service import create_website_record
        website_id = await create_website_record(url, user_email, task_id)
        
        if not website_id:
            raise HTTPException(status_code=500, detail="Failed to create website record")
        
        # Queue scraping task
        success = redis_queue.publish_web_task(
            celery_task_id=task_id
        )
        
        if success:
            logger.info(f"✅ Queued website scraping task: {task_id}")
            return {
                "success": True,
                "message": "Website scraping started successfully",
                "task_id": task_id,
                "website_id": str(website_id),
                "url": url,
                "status": "Queued"
            }
        else:
            raise HTTPException(status_code=500, detail="Failed to queue scraping task")
                
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
    try:
        from shared.db import get_db_connection
        async with get_db_connection() as conn:
            # Test database connection
            await conn.fetchval("SELECT 1")
            
        return {
            "status": "healthy",
            "service": "knowledgebase_ingestion",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return {
            "status": "unhealthy",
            "service": "knowledgebase_ingestion",
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }
