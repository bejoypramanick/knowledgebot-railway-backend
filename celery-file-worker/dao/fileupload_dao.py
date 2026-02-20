"""
File Upload Data Access Object for Celery File Worker
Handles database operations for file uploads - mirrors web worker pattern
"""
from typing import Any, Dict, Optional
import json

from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("fileupload_dao", "celery-file-worker")


class FileUploadDAO:
    def __init__(self):
        pass

    async def update_file_status(self, file_id: int, status: str, error_message: str = None) -> bool:
        """Update file processing status."""
        logger.info(f"💾 [FILE_UPDATE_STATUS] Updating file {file_id} status to: {status}")

        query = """
            UPDATE file_uploads
            SET processing_status = $2, error_message = $3, updated_at = NOW()
            WHERE id = $1
        """
        params = [file_id, status, error_message]

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, *params)
                logger.log_db_query(query, params, result)
                
                if result != "UPDATE 0":
                    logger.info(f"✅ [FILE_UPDATE_STATUS_SUCCESS] Status updated to: {status}")
                    return True
                else:
                    logger.warning(f"⚠️  [FILE_UPDATE_STATUS_NO_ROWS] No rows updated (file_id {file_id} may not exist)")
                    return False
        except Exception as e:
            logger.error(f"❌ [FILE_UPDATE_STATUS_ERROR] Failed to update file status: {e}")
            logger.log_db_query(query, params, error=e)
            return False

    async def update_file_with_processing_data(
        self,
        file_id: int,
        gemini_file_name: str,
        gemini_file_uri: str,
        gemini_state: str,
        file_size: int,
        char_count: int,
        sha256_hash: str,
        metadata: Dict[str, Any],
        processed_by_docling: bool = False,
        docling_processing_time_ms: int = None,
        docling_images_extracted: int = 0,
        docling_images_with_ocr: int = 0,
        original_file_extension: str = None,
        original_mime_type: str = None
    ) -> bool:
        """
        Update file record with all processing data after successful upload.
        Mirrors the web worker's update_website_with_page_data pattern.
        
        Returns: True on success, False on failure
        """
        logger.info(f"💾 [UPDATE_FILE_DATA] Updating file {file_id} with processing data")
        logger.info(f"   Gemini File: {gemini_file_name}")
        logger.info(f"   File Size: {file_size:,} bytes")
        logger.info(f"   Char Count: {char_count:,}")
        logger.info(f"   Processed by Docling: {processed_by_docling}")

        query = """
            UPDATE file_uploads
            SET gemini_file_name = $1,
                gemini_file_uri = $2,
                gemini_state = $3,
                file_size = $4,
                char_count = $5,
                sha256_hash = $6,
                metadata = $7::jsonb,
                processed_by_docling = $8,
                docling_processing_time_ms = $9,
                docling_images_extracted = $10,
                docling_images_with_ocr = $11,
                original_file_extension = $12,
                original_mime_type = $13,
                processing_status = 'completed',
                updated_at = NOW()
            WHERE id = $14
        """

        params = [
            gemini_file_name,
            gemini_file_uri,
            gemini_state,
            file_size,
            char_count,
            sha256_hash,
            json.dumps(metadata),
            processed_by_docling,
            docling_processing_time_ms,
            docling_images_extracted,
            docling_images_with_ocr,
            original_file_extension,
            original_mime_type,
            file_id
        ]

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                await conn.execute(query, *params)
                logger.info(f"✅ [UPDATE_FILE_DATA_SUCCESS] File record updated and marked as completed")
                logger.log_db_query(query, params, "UPDATE succeeded")
                return True
        except Exception as e:
            logger.error(f"❌ [UPDATE_FILE_DATA_ERROR] Failed to update file: {e}")
            logger.error(f"   File ID: {file_id}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            logger.log_db_query(query, params, error=e)
            return False

    async def get_file_by_task_id(self, celery_task_id: str) -> Optional[Dict[str, Any]]:
        """Get file record by celery_task_id."""
        query = """
            SELECT id, user_role_id, original_filename, display_name, file_extension,
                   s3_key, file_size, mime_type, sha256_hash, processing_status,
                   celery_task_id, created_at, updated_at
            FROM file_uploads 
            WHERE celery_task_id = $1
        """
        
        try:
            logger.log_db_operation(query, {"celery_task_id": celery_task_id})
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, celery_task_id)
                logger.log_db_query(query, {"celery_task_id": celery_task_id}, result)
                
                if result:
                    return dict(result)
                return None
        except Exception as e:
            logger.error(f"❌ Error getting file by task_id: {e}")
            logger.log_db_query(query, {"celery_task_id": celery_task_id}, error=e)
            return None
