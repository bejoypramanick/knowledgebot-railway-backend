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
from shared.celery_dispatcher import file_celery, web_celery
from shared.task_control import TaskControl
from shared.vector_dao import vector_dao
from shared.redis_ui_cache import invalidate_kb_caches

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
            # Invalidate cache so the pending record shows up in UI
            await invalidate_kb_caches()
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


async def get_file_by_id(file_id: str) -> Optional[Dict[str, Any]]:
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


async def update_file_status(file_id: str, status: str, error_message: str = None) -> bool:
    """Update file processing status."""
    try:
        dao = get_fileupload_dao()
        res = await dao.update_file_status(file_id, status, error_message)
        if res:
            await invalidate_kb_caches()
        return res
    except Exception as e:
        logger.error(f"❌ Error updating file status: {e}")
        return False


async def queue_file_for_processing(file_id: str, celery_task_id: str) -> bool:
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


async def delete_file(file_id: str) -> Dict[str, Any]:
    """
    Delete file atomically with complete cleanup
    """
    from .atomic_deletion_service import atomic_deletion_service
    
    logger.info(f"�️ [DELETE_FILE] Starting atomic file deletion for ID: {file_id}")
    
    result = await atomic_deletion_service.delete_file_atomically(file_id)
    
    if result["success"]:
        logger.info(f"✅ [DELETE_FILE] File {file_id} deleted successfully")
    else:
        logger.error(f"❌ [DELETE_FILE] Failed to delete file {file_id}: {result.get('error')}")
    
    return result


async def validate_file_upload(file: UploadFile, file_size: int, replace_existing: bool = False) -> Dict[str, Any]:
    """
    Validate file upload and return validation result.
    Includes duplicate check against active files.
    
    Args:
        file: The uploaded file
        file_size: Size of the file in bytes
        replace_existing: If True, mark existing file as deleted and allow upload
    """
    logger.info("✔️  [VALIDATION_START] Starting file validation")
    logger.info(f"   Replace existing: {replace_existing}")

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
        mime_valid, mime_error = validate_mime_type(file.content_type or "", sanitized_filename)
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

        # Check for duplicate filename (only active files)
        logger.info(f"🔍 [DUPLICATE_CHECK] Checking for existing files with name: {original_filename}")
        from shared.sqlalchemy_db import get_db_session
        from sqlalchemy import text

        async with get_db_session() as session:
            # Get all files with this name
            result = await session.execute(
                text("SELECT id, original_filename, processing_status FROM file_uploads WHERE original_filename = :filename ORDER BY id DESC"),
                {"filename": original_filename}
            )
            all_files = result.mappings().all()
            logger.info(f"🔍 [DUPLICATE_CHECK_ALL] Found {len(all_files)} total files with name '{original_filename}':")
            for f in all_files:
                logger.info(f"   - ID={f['id']}, status={f['processing_status']}")

            # Check for active files (exclude failed, deleted, cancelled)
            result = await session.execute(
                text("SELECT id, original_filename, processing_status FROM file_uploads WHERE original_filename = :filename AND processing_status IN ('pending', 'processing', 'queued', 'completed') LIMIT 1"),
                {"filename": original_filename}
            )
            existing_active = result.mappings().first()

            if existing_active:
                if replace_existing:
                    # Mark existing file as deleted
                    logger.info(f"🔄 [REPLACE] Marking existing file as deleted: ID={existing_active['id']}")
                    await session.execute(
                        text("UPDATE file_uploads SET processing_status = 'deleted', updated_at = CURRENT_TIMESTAMP WHERE id = :id"),
                        {"id": existing_active['id']}
                    )
                    await session.commit()
                    logger.info(f"✅ [REPLACE] Existing file marked as deleted, allowing new upload")
                else:
                    logger.warning(f"🔍 [DUPLICATE_CHECK] Found ACTIVE file: ID={existing_active['id']}, filename={existing_active['original_filename']}, status={existing_active['processing_status']}")
                    return {
                        "valid": False,
                        "is_duplicate": True,
                        "error": f"File '{original_filename}' already exists",
                        "reason": "filename_exists",
                        "match_type": "filename",
                        "existing_file_id": str(existing_active['id']),
                        "existing_file_name": existing_active['original_filename'],
                        "existing_file_status": existing_active['processing_status'],
                        "filename": sanitized_filename,
                        "duplicate_file_id": existing_active['id']
                    }
            else:
                logger.info(f"🔍 [DUPLICATE_CHECK] No active duplicate found for: {original_filename}")

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
    Completely clear the knowledge base while preserving audit rows.

    Operations performed:
    1. Stop running ingestion tasks
    2. Delete all knowledge-base files from S3 storage
    3. Clear Redis/Celery queues
    4. Mark all file records with status='deleted' (soft delete)
    5. Mark all website records with status='deleted' (soft delete)

    Database records are retained with status='deleted' for:
    - Audit trail and compliance
    - Recovery purposes
    - Historical tracking
    """
    logger.info("=" * 80)
    logger.info("🗑️  [DELETE_ALL_START] Clearing entire knowledge base")
    logger.info("=" * 80)

    deleted_websites = 0
    s3_files_deleted = 0
    errors = []

    try:
        from shared.sqlalchemy_db import get_db_session
        from sqlalchemy import text
        # Step 1: Stop all running tasks FIRST
        logger.info("🔴 [TASK_CONTROL] Stopping all Celery tasks...")
        try:
            success = TaskControl.stop_all_tasks()
            if success:
                logger.info("   ✅ All Celery tasks stopped (revoked + flags set)")
            else:
                logger.warning("   ⚠️ Some tasks may not have been stopped")
        except Exception as e:
            logger.warning(f"⚠️ [TASK_CONTROL_ERROR] Error stopping tasks: {e}")
            # Don't add to errors - task termination is best-effort

        # Step 1b: Removed docling RQ jobs cancellation as Kreuzberg doesn't use RQ

        # Step 2: Delete all files from S3 (EXCEPT widget configuration images)
        logger.info("🪣 [S3_DELETE] Deleting all knowledge base files from S3 (excluding widget images)...")
        s3_files_deleted = 0
        try:
            from shared.s3_file_storage import S3FileStorage

            async with get_db_session() as session:
                # Get all files with S3 keys
                result = await session.execute(
                    text("SELECT id, original_filename, s3_key FROM file_uploads WHERE s3_key IS NOT NULL")
                )
                files_with_s3 = result.mappings().all()
                logger.info(f"   Found {len(files_with_s3)} files to delete from S3")

                if files_with_s3:
                    s3_storage = S3FileStorage()
                    
                    # Filter out widget configuration images (agent-icon/ and bubble-icon/ prefixes)
                    # These are stored in the same S3 bucket but should NOT be deleted
                    knowledge_base_keys = [
                        file_record['s3_key'] 
                        for file_record in files_with_s3 
                        if not file_record['s3_key'].startswith('agent-icon/') 
                        and not file_record['s3_key'].startswith('bubble-icon/')
                    ]
                    
                    excluded_count = len(files_with_s3) - len(knowledge_base_keys)
                    if excluded_count > 0:
                        logger.info(f"   ℹ️  Excluding {excluded_count} widget configuration images from deletion")

                    # Use batch delete for efficiency
                    deleted_count, failed_count = await s3_storage.delete_files_batch(knowledge_base_keys)
                    s3_files_deleted = deleted_count

                    logger.info(f"   ✅ Deleted {deleted_count} knowledge base files from S3")
                    if excluded_count > 0:
                        logger.info(f"   ✅ Preserved {excluded_count} widget configuration images")
                    if failed_count > 0:
                        logger.warning(f"   ⚠️  Failed to delete {failed_count} files from S3")
                        errors.append(f"Failed to delete {failed_count} files from S3")
        except Exception as e:
            logger.error(f"❌ [S3_DELETE_ERROR] Error deleting files from S3: {e}")
            errors.append(f"S3 deletion failed: {e}")

        # Step 3: Mark all files as deleted in database (soft delete - don't remove records)
        logger.info("💾 [DB_UPDATE_FILES] Marking all files as deleted in database...")
        try:
            async with get_db_session() as session:
                # Ensure CHECK constraint allows 'deleted' status (auto-migrate)
                await session.execute(text(
                    "ALTER TABLE file_uploads DROP CONSTRAINT IF EXISTS valid_processing_status"
                ))
                await session.execute(text(
                    "ALTER TABLE file_uploads DROP CONSTRAINT IF EXISTS file_uploads_processing_status_check"
                ))
                await session.execute(text("""
                    ALTER TABLE file_uploads ADD CONSTRAINT valid_processing_status CHECK (
                        processing_status::text = ANY (ARRAY[
                            'pending'::text, 'processing'::text, 'completed'::text,
                            'failed'::text, 'cancelled'::text, 'deleted'::text
                        ])
                    )
                """))
                await session.execute(
                    text("UPDATE file_uploads SET processing_status = 'deleted', updated_at = CURRENT_TIMESTAMP")
                )
                await session.commit()
                logger.info(f"   ✅ All file records marked as deleted (status updated, records retained)")
        except Exception as e:
            logger.error(f"❌ [DB_UPDATE_FILES_ERROR] Error marking files as deleted: {e}")
            errors.append(f"File status update failed: {e}")

        # Step 4: Mark all websites as deleted in database (soft delete - don't remove records)
        logger.info("💾 [DB_UPDATE_WEBSITES] Marking all websites as deleted in database...")
        try:
            async with get_db_session() as session:
                result = await session.execute(text("SELECT id, original_url FROM scraped_websites"))
                websites = result.mappings().all()
                logger.info(f"   Found {len(websites)} websites to mark as deleted")

                await session.execute(
                    text("UPDATE scraped_websites SET processing_status = 'deleted', updated_at = CURRENT_TIMESTAMP")
                )
                await session.commit()
                deleted_websites = len(websites)
                logger.info(f"   ✅ All {deleted_websites} website records marked as deleted (status updated, records retained)")
        except Exception as e:
            logger.error(f"❌ [DB_DELETE_WEBSITES_ERROR] Error deleting websites: {e}")
            errors.append(f"Website deletion failed: {e}")

        # Step 5: CLEAR Vector Knowledge Base (document_chunks table)
        logger.info("💾 [DB_CLEAR_RAG] Emptying document_chunks table (clearing vector embeddings)...")
        try:
            chunks_cleared = await vector_dao.clear_all_chunks()
            logger.info(f"   ✅ [DB_CLEAR_RAG_SUCCESS] Cleared {chunks_cleared} vector chunks from document_chunks")
            # Vacuum the table after full reset
            await vector_dao.vacuum_document_chunks()
        except Exception as e:
            logger.error(f"❌ [DB_CLEAR_RAG_ERROR] Error clearing document_chunks: {e}")
            errors.append(f"Vector knowledge base clear failed: {e}")

        logger.info("=" * 80)
        logger.info("✅ [DELETE_ALL_COMPLETE] Knowledge base clear completed")
        logger.info("=" * 80)
        logger.info(f"📊 [RESULT] Files deleted from S3: {s3_files_deleted}")
        logger.info(f"📊 [RESULT] Websites marked as deleted: {deleted_websites}")
        logger.info(f"📊 [RESULT] Vector chunks cleared: {chunks_cleared}")
        logger.info(f"📊 [RESULT] Redis queues cleared: 2 (file_processing, web_crawling)")

        if errors:
            logger.warning(f"⚠️  [ERRORS] {len(errors)} error(s) occurred:")
            for error in errors:
                logger.warning(f"   - {error}")

        return {
            "success": len(errors) == 0,
            "message": "Knowledge base cleared successfully" if len(errors) == 0 else "Knowledge base cleared with errors",
            "s3_files_deleted": s3_files_deleted,
            "websites_marked_deleted": deleted_websites,
            "chunks_cleared": chunks_cleared,
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
            "s3_files_deleted": 0,
            "websites_marked_deleted": 0,
            "errors": [str(e)]
        }
