"""
File Upload Service Layer
Handles business logic for file upload operations
"""
import asyncio
import os
import time
from datetime import datetime
from typing import Any, Dict, List, Optional

from fastapi import UploadFile, HTTPException

from shared.otel_logger import get_otel_logger
from knowledgebase_ingestion.core.ai import get_genai_client
from knowledgebase_ingestion.core.config import settings
from knowledgebase_ingestion.utils.validation import (
    validate_file_extension, validate_file_size, validate_mime_type,
    sanitize_filename
)
from knowledgebase_ingestion.dao.fileupload_dao import FileUploadDAO
from shared.redis_message_queue import RedisMessageQueue

logger = get_otel_logger("fileupload_service", "knowledgebase-ingestion")

# Singleton DAO instance
_fileupload_dao = None

def get_fileupload_dao() -> FileUploadDAO:
    """Get singleton FileUploadDAO instance."""
    global _fileupload_dao
    if _fileupload_dao is None:
        _fileupload_dao = FileUploadDAO()
    return _fileupload_dao


async def create_file_record(record_data: Dict[str, Any]) -> Optional[str]:
    """
    Create file record with validation.
    Delegates to DAO layer for database operations.
    """
    try:
        dao = get_fileupload_dao()
        return await dao.create_file_record(record_data)
    except Exception as e:
        logger.error(f"❌ Error creating file record: {e}")
        return None


async def get_pending_files() -> List[Dict[str, Any]]:
    """Get all files with pending or processing status."""
    try:
        dao = get_fileupload_dao()
        return await dao.get_pending_files()
    except Exception as e:
        logger.error(f"❌ Error getting pending files: {e}")
        return []


async def get_file_by_id(file_id: int) -> Optional[Dict[str, Any]]:
    """Get file record by ID."""
    try:
        dao = get_fileupload_dao()
        return await dao.get_file_by_id(file_id)
    except Exception as e:
        logger.error(f"❌ Error getting file by ID: {e}")
        return None


async def cancel_files() -> int:
    """Cancel all pending/processing files."""
    try:
        dao = get_fileupload_dao()
        return await dao.cancel_files()
    except Exception as e:
        logger.error(f"❌ Error cancelling files: {e}")
        return 0


async def update_file_status(file_id: int, status: str, error_message: str = None) -> bool:
    """Update file processing status."""
    try:
        dao = get_fileupload_dao()
        return await dao.update_file_status(file_id, status, error_message)
    except Exception as e:
        logger.error(f"❌ Error updating file status: {e}")
        return False


async def queue_file_for_processing(file_id: int, celery_task_id: str) -> bool:
    """
    Queue file for processing via Redis.
    """
    try:
        redis_queue = RedisMessageQueue()
        success = redis_queue.publish_file_task(celery_task_id=celery_task_id)
        
        if success:
            logger.info(f"✅ Queued file {file_id} for processing")
            return True
        else:
            logger.error(f"❌ Failed to queue file {file_id} for processing")
            return False
    except Exception as e:
        logger.error(f"❌ Error queuing file for processing: {e}")
        return False


async def queue_file_for_deletion(file_id: int) -> Dict[str, Any]:
    """
    Queue file for deletion if currently processing.
    """
    try:
        # Get file details first
        file_record = await get_file_by_id(file_id)
        if not file_record:
            return {
                "success": False,
                "error": "File not found"
            }

        # Check if file is currently processing
        if file_record['processing_status'] in ('pending', 'processing'):
            # Generate task ID for deletion
            import uuid
            celery_task_id = str(uuid.uuid4())
            
            # Update file status to queued for deletion
            await update_file_status(file_id, 'queued_for_deletion')
            
            # Queue deletion task
            success = await queue_file_for_processing(file_id, celery_task_id)
            
            if success:
                logger.info(f"✅ Queued file {file_id} for deletion")
                return {
                    "success": True,
                    "message": "File deletion queued successfully",
                    "task_id": celery_task_id,
                    "file_id": str(file_id)
                }
            else:
                return {
                    "success": False,
                    "error": "Failed to queue deletion task"
                }
        else:
            # File is not processing, delete directly
            from knowledgebase_ingestion.service.file_service import FileService
            file_service = FileService()
            result = await file_service.delete_file_logic(str(file_id))
            
            return result
    except Exception as e:
        logger.error(f"❌ Error queuing file for deletion: {e}")
        return {
            "success": False,
            "error": str(e)
        }


async def validate_file_upload(file: UploadFile, file_size: int) -> Dict[str, Any]:
    """
    Validate file upload and return validation result.
    """
    try:
        # Sanitize filename
        original_filename = file.filename or "unknown"
        sanitized_filename = sanitize_filename(original_filename)
        
        # Validate file extension
        ext_valid, ext_error = validate_file_extension(sanitized_filename)
        if not ext_valid:
            return {
                "valid": False,
                "error": ext_error,
                "filename": sanitized_filename
            }
        
        # Validate MIME type
        mime_valid, mime_error = validate_mime_type(file.content_type or "")
        if not mime_valid:
            return {
                "valid": False,
                "error": mime_error,
                "filename": sanitized_filename
            }
        
        # Validate file size
        size_valid, size_error = validate_file_size(file_size)
        if not size_valid:
            return {
                "valid": False,
                "error": size_error,
                "filename": sanitized_filename
            }
        
        return {
            "valid": True,
            "filename": sanitized_filename,
            "original_filename": original_filename,
            "file_size": file_size,
            "mime_type": file.content_type
        }
    except Exception as e:
        logger.error(f"❌ Error validating file upload: {e}")
        return {
            "valid": False,
            "error": f"Validation error: {str(e)}",
            "filename": file.filename or "unknown"
        }
