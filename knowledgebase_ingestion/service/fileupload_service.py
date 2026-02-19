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
    logger.info("💾 [DB_INSERT_START] Creating file record in database")
    logger.info(f"📝 [DB_PARAMS] Record data:")
    logger.info(f"   user_id: {record_data.get('user_id')}")
    logger.info(f"   original_filename: {record_data.get('original_filename')}")
    logger.info(f"   file_display_name: {record_data.get('file_display_name')}")
    logger.info(f"   size_bytes: {record_data.get('size_bytes')}")
    logger.info(f"   mime_type: {record_data.get('mime_type')}")
    logger.info(f"   processing_status: {record_data.get('processing_status')}")
    logger.info(f"   source: {record_data.get('source')}")
    logger.info(f"   sha256_hash: {record_data.get('sha256_hash')}")
    logger.info(f"   s3_key: {record_data.get('s3_key')}")
    logger.info(f"   celery_task_id: {record_data.get('celery_task_id')}")

    try:
        dao = get_fileupload_dao()
        file_id = await dao.create_file_record(record_data)

        if file_id:
            logger.info(f"✅ [DB_INSERT_SUCCESS] File record created with ID: {file_id}")
            logger.info(f"   Filename: {record_data.get('original_filename')}")
            return file_id
        else:
            logger.error(f"❌ [DB_INSERT_FAILED] Failed to create file record (returned None)")
            return None
    except Exception as e:
        logger.error(f"❌ [DB_INSERT_ERROR] Error creating file record: {e}")
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
    logger.info("=" * 80)
    logger.info("⏹️  [CANCEL_ALL_START] Cancelling all pending/processing files")
    logger.info("=" * 80)

    try:
        dao = get_fileupload_dao()
        logger.info("💾 [DB_UPDATE] Executing UPDATE query to mark files as cancelled...")
        logger.info("   SQL: UPDATE file_uploads SET processing_status = 'cancelled'")
        logger.info("   WHERE processing_status IN ('pending', 'processing')")

        cancelled_count = await dao.cancel_files()

        logger.info("=" * 80)
        logger.info(f"✅ [CANCEL_ALL_COMPLETE] All files cancelled successfully")
        logger.info("=" * 80)
        logger.info(f"📊 [RESULT] Files cancelled: {cancelled_count}")

        return cancelled_count

    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"❌ [CANCEL_ALL_ERROR] Error cancelling files: {e}")
        logger.error("=" * 80)
        logger.error(f"   Error Type: {type(e).__name__}")
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
    logger.info("=" * 80)
    logger.info(f"🗑️  [DELETE_START] File deletion process started for file ID: {file_id}")
    logger.info("=" * 80)

    try:
        # Get file details first
        logger.info(f"🔍 [LOOKUP] Fetching file record from database...")
        file_record = await get_file_by_id(file_id)

        if not file_record:
            logger.error(f"❌ [LOOKUP_FAILED] File ID {file_id} not found in database")
            return {
                "success": False,
                "error": "File not found"
            }

        logger.info(f"✅ [LOOKUP_SUCCESS] File found in database")
        logger.info(f"   ID: {file_record['id']}")
        logger.info(f"   Filename: {file_record['original_filename']}")
        logger.info(f"   Status: {file_record['processing_status']}")

        # Check if file is currently processing
        current_status = file_record['processing_status']
        logger.info(f"🔄 [STATUS_CHECK] Current file status: {current_status}")

        if current_status in ('pending', 'processing'):
            logger.info(f"📋 [QUEUE_DELETE] File is {current_status}, queueing for deletion...")

            # Generate task ID for deletion
            import uuid
            celery_task_id = str(uuid.uuid4())
            logger.info(f"   Generated Celery Task ID: {celery_task_id}")

            # Update file status to queued for deletion
            logger.info(f"💾 [STATUS_UPDATE] Updating file status to 'queued_for_deletion'...")
            status_updated = await update_file_status(file_id, 'queued_for_deletion')
            logger.info(f"   Status Update Result: {status_updated}")

            # Queue deletion task
            logger.info(f"📤 [QUEUE_TASK] Queuing file deletion task...")
            success = await queue_file_for_processing(file_id, celery_task_id)

            if success:
                logger.info("=" * 80)
                logger.info(f"✅ [DELETE_QUEUED] File deletion successfully queued")
                logger.info("=" * 80)
                logger.info(f"   File ID: {file_id}")
                logger.info(f"   Task ID: {celery_task_id}")
                logger.info(f"   Status: queued_for_deletion")

                return {
                    "success": True,
                    "message": "File deletion queued successfully",
                    "task_id": celery_task_id,
                    "file_id": str(file_id)
                }
            else:
                logger.error(f"❌ [QUEUE_FAILED] Failed to queue deletion task for file {file_id}")
                return {
                    "success": False,
                    "error": "Failed to queue deletion task"
                }
        else:
            # File is not processing, delete directly
            logger.info(f"⚡ [DIRECT_DELETE] File is {current_status}, deleting directly...")
            logger.info(f"   Loading FileService...")

            from knowledgebase_ingestion.service.file_service import FileService
            file_service = FileService()

            logger.info(f"   Calling delete_file_logic() for file ID {file_id}...")
            result = await file_service.delete_file_logic(str(file_id))

            logger.info("=" * 80)
            logger.info(f"🗑️  [DIRECT_DELETE_COMPLETE] Direct deletion completed")
            logger.info("=" * 80)
            logger.info(f"   Success: {result.get('success')}")
            logger.info(f"   Message: {result.get('message')}")

            return result

    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"❌ [DELETE_ERROR] Error queuing file for deletion: {e}")
        logger.error("=" * 80)
        logger.error(f"   File ID: {file_id}")
        logger.error(f"   Error Type: {type(e).__name__}")

        return {
            "success": False,
            "error": str(e)
        }


async def validate_file_upload(file: UploadFile, file_size: int) -> Dict[str, Any]:
    """
    Validate file upload and return validation result.
    """
    logger.info("✔️  [VALIDATION_START] Starting file validation")

    try:
        # Sanitize filename
        original_filename = file.filename or "unknown"
        logger.info(f"📝 [SANITIZE] Original filename: {original_filename}")

        sanitized_filename = sanitize_filename(original_filename)
        logger.info(f"📝 [SANITIZE] Sanitized filename: {sanitized_filename}")

        # Validate file extension
        logger.info(f"🔍 [EXT_CHECK] Validating file extension...")
        ext_valid, ext_error = validate_file_extension(sanitized_filename)
        logger.info(f"   Extension valid: {ext_valid}")

        if not ext_valid:
            logger.error(f"❌ [EXT_INVALID] Extension validation failed: {ext_error}")
            return {
                "valid": False,
                "error": ext_error,
                "filename": sanitized_filename
            }

        logger.info(f"✅ [EXT_VALID] File extension is valid")

        # Validate MIME type
        logger.info(f"🔍 [MIME_CHECK] Validating MIME type: {file.content_type}")
        mime_valid, mime_error = validate_mime_type(file.content_type or "")
        logger.info(f"   MIME type valid: {mime_valid}")

        if not mime_valid:
            logger.error(f"❌ [MIME_INVALID] MIME type validation failed: {mime_error}")
            return {
                "valid": False,
                "error": mime_error,
                "filename": sanitized_filename
            }

        logger.info(f"✅ [MIME_VALID] MIME type is valid")

        # Validate file size
        logger.info(f"🔍 [SIZE_CHECK] Validating file size: {file_size} bytes")
        size_valid, size_error = validate_file_size(file_size)
        logger.info(f"   File size valid: {size_valid}")

        if not size_valid:
            logger.error(f"❌ [SIZE_INVALID] File size validation failed: {size_error}")
            return {
                "valid": False,
                "error": size_error,
                "filename": sanitized_filename
            }

        logger.info(f"✅ [SIZE_VALID] File size is valid")

        logger.info("=" * 80)
        logger.info("✅ [VALIDATION_SUCCESS] All file validations passed")
        logger.info("=" * 80)
        logger.info(f"📝 [RESULT] Sanitized filename: {sanitized_filename}")
        logger.info(f"📝 [RESULT] Original filename: {original_filename}")
        logger.info(f"📝 [RESULT] File size: {file_size} bytes")
        logger.info(f"📝 [RESULT] MIME type: {file.content_type}")

        return {
            "valid": True,
            "filename": sanitized_filename,
            "original_filename": original_filename,
            "file_size": file_size,
            "mime_type": file.content_type
        }

    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"❌ [VALIDATION_ERROR] Error validating file upload: {e}")
        logger.error("=" * 80)
        logger.error(f"   File: {file.filename}")
        logger.error(f"   Size: {file_size} bytes")
        logger.error(f"   Error Type: {type(e).__name__}")

        return {
            "valid": False,
            "error": f"Validation error: {str(e)}",
            "filename": file.filename or "unknown"
        }


async def delete_all_knowledge() -> Dict[str, Any]:
    """
    Soft delete all files and websites from knowledge base.

    Operations performed:
    1. Removes all files from Gemini FileSearch store
    2. Clears Redis task queues (file_processing, web_crawling)
    3. Marks all file records with status='deleted' (soft delete)
    4. Marks all website records with status='deleted' (soft delete)

    Database records are retained with status='deleted' for:
    - Audit trail and compliance
    - Recovery purposes
    - Historical tracking
    """
    logger.info("=" * 80)
    logger.info("🗑️  [DELETE_ALL_START] Clearing entire knowledge base")
    logger.info("=" * 80)

    deleted_files = 0
    deleted_websites = 0
    errors = []

    try:
        from shared.db import get_db_connection
        from knowledgebase_ingestion.core.ai import get_genai_client

        # Step 1: Delete all files from Gemini FileSearch
        logger.info("📝 [GEMINI_DELETE] Deleting files from Gemini FileSearch...")
        try:
            async with get_db_connection() as conn:
                # Get all files with gemini_file_name
                files = await conn.fetch(
                    "SELECT id, original_filename, gemini_file_name FROM file_uploads WHERE gemini_file_name IS NOT NULL"
                )
                logger.info(f"   Found {len(files)} files to delete from Gemini")

                genai_client = get_genai_client()
                if genai_client:
                    for file_record in files:
                        try:
                            genai_client.files.delete(name=file_record['gemini_file_name'])
                            deleted_files += 1
                            logger.info(f"   ✅ Deleted from Gemini: {file_record['original_filename']}")
                        except Exception as gem_err:
                            logger.warning(f"   ⚠️  Could not delete from Gemini: {file_record['gemini_file_name']} - {gem_err}")
                            errors.append(f"Gemini delete failed for {file_record['original_filename']}: {gem_err}")
                else:
                    logger.error("   ❌ Gemini client not available")
                    errors.append("Gemini client not available")
        except Exception as e:
            logger.error(f"❌ [GEMINI_DELETE_ERROR] Error deleting from Gemini: {e}")
            errors.append(f"Gemini deletion failed: {e}")

        # Step 2: Clear Redis queues
        logger.info("🔴 [REDIS_CLEAR] Clearing Redis task queues...")
        try:
            redis_queue = RedisMessageQueue()
            redis_queue.clear_file_task_queue()
            redis_queue.clear_web_task_queue()
            logger.info("   ✅ Redis queues cleared")
        except Exception as e:
            logger.error(f"❌ [REDIS_CLEAR_ERROR] Error clearing Redis: {e}")
            errors.append(f"Redis clear failed: {e}")

        # Step 3: Mark all files as deleted in database (soft delete - don't remove records)
        logger.info("💾 [DB_UPDATE_FILES] Marking all files as deleted in database...")
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(
                    "UPDATE file_uploads SET processing_status = 'deleted', updated_at = NOW()"
                )
                logger.info(f"   ✅ All file records marked as deleted (status updated, records retained)")
        except Exception as e:
            logger.error(f"❌ [DB_UPDATE_FILES_ERROR] Error marking files as deleted: {e}")
            errors.append(f"File status update failed: {e}")

        # Step 4: Mark all websites as deleted in database (soft delete - don't remove records)
        logger.info("💾 [DB_UPDATE_WEBSITES] Marking all websites as deleted in database...")
        try:
            async with get_db_connection() as conn:
                websites = await conn.fetch("SELECT id, original_url FROM scraped_websites")
                logger.info(f"   Found {len(websites)} websites to mark as deleted")

                result = await conn.execute(
                    "UPDATE scraped_websites SET processing_status = 'deleted', updated_at = NOW()"
                )
                deleted_websites = len(websites)
                logger.info(f"   ✅ All {deleted_websites} website records marked as deleted (status updated, records retained)")
        except Exception as e:
            logger.error(f"❌ [DB_DELETE_WEBSITES_ERROR] Error deleting websites: {e}")
            errors.append(f"Website deletion failed: {e}")

        logger.info("=" * 80)
        logger.info("✅ [DELETE_ALL_COMPLETE] Knowledge base clear completed")
        logger.info("=" * 80)
        logger.info(f"📊 [RESULT] Files deleted: {deleted_files}")
        logger.info(f"📊 [RESULT] Websites deleted: {deleted_websites}")
        logger.info(f"📊 [RESULT] Redis queues cleared: 2 (file_processing, web_crawling)")

        if errors:
            logger.warning(f"⚠️  [ERRORS] {len(errors)} error(s) occurred:")
            for error in errors:
                logger.warning(f"   - {error}")

        return {
            "success": len(errors) == 0,
            "message": "Knowledge base cleared successfully" if not errors else "Knowledge base cleared with errors",
            "deleted_files": deleted_files,
            "deleted_websites": deleted_websites,
            "redis_queues_cleared": 2,
            "errors": errors if errors else None
        }

    except Exception as e:
        logger.error("=" * 80)
        logger.error(f"❌ [DELETE_ALL_ERROR] Error clearing knowledge base: {e}")
        logger.error("=" * 80)

        return {
            "success": False,
            "message": f"Error clearing knowledge base: {str(e)}",
            "deleted_files": deleted_files,
            "deleted_websites": deleted_websites,
            "errors": [str(e)]
        }
