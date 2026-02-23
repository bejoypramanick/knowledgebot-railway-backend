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

    async def get_file_by_id(self, file_id: int) -> Optional[Dict[str, Any]]:
        """Get file record by file ID."""
        query = """
            SELECT id, user_role_id, original_filename, display_name,
                   s3_key, file_size, mime_type, processing_status
            FROM file_uploads
            WHERE id = $1
        """

        try:
            logger.log_db_operation(query, {"file_id": file_id})
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, file_id)
                logger.log_db_query(query, {"file_id": file_id}, result)

                if result:
                    logger.info(f"✅ [DB_QUERY] File found: {result['original_filename']}")
                    return dict(result)
                else:
                    logger.error(f"❌ [DB_QUERY] No file found for file_id: {file_id}")
                    return None
        except Exception as e:
            logger.error(f"❌ Error getting file by ID: {e}")
            logger.log_db_query(query, {"file_id": file_id}, error=e)
            return None

    async def check_duplicate_file(self, original_filename: str, exclude_file_id: Optional[int] = None) -> Optional[Dict[str, Any]]:
        """Check if file with same name exists in database (only active files)."""
        try:
            async with get_db_connection() as conn:
                # First, log ALL files with this name to debug
                all_query = "SELECT id, original_filename, processing_status FROM file_uploads WHERE original_filename = $1 ORDER BY id DESC"
                all_files = await conn.fetch(all_query, original_filename)
                logger.info(f"🔍 [DUPLICATE_CHECK_ALL] Found {len(all_files)} total files with name '{original_filename}':")
                for f in all_files:
                    logger.info(f"   - ID={f['id']}, status={f['processing_status']}")

                # Only check active files (exclude failed, deleted, cancelled)
                # Also exclude the current file being processed
                if exclude_file_id:
                    query = "SELECT id, original_filename, processing_status FROM file_uploads WHERE original_filename = $1 AND id != $2 AND processing_status IN ('pending', 'processing', 'queued', 'completed') LIMIT 1"
                    record = await conn.fetchrow(query, original_filename, exclude_file_id)
                    logger.info(f"🔍 [DUPLICATE_CHECK] Excluding current file ID={exclude_file_id} from check")
                else:
                    query = "SELECT id, original_filename, processing_status FROM file_uploads WHERE original_filename = $1 AND processing_status IN ('pending', 'processing', 'queued', 'completed') LIMIT 1"
                    record = await conn.fetchrow(query, original_filename)

                if record:
                    logger.warning(f"🔍 [DUPLICATE_CHECK] Found ACTIVE duplicate: ID={record['id']}, filename={record['original_filename']}, status={record['processing_status']}")
                else:
                    logger.info(f"🔍 [DUPLICATE_CHECK] No active duplicate found for: {original_filename}")

                return record if record else None
        except Exception as e:
            logger.error(f"❌ Error checking duplicate: {e}")
            return None

    async def get_admin_user_role_id(self, user_email: Optional[str] = None) -> Optional[str]:
        """Get admin user role ID from database."""
        try:
            async with get_db_connection() as conn:
                # Get admin role first
                admin_role = await conn.fetchval(
                    "SELECT id FROM roles WHERE role_name = 'admin' LIMIT 1"
                )

                if not admin_role:
                    logger.warning("⚠️ Admin role not found in database")
                    return None

                # Get user role mapping for this email
                user_role = await conn.fetchval(
                    "SELECT user_role_id FROM user_role_mapping WHERE email = $1 AND role_id = $2 LIMIT 1",
                    user_email or 'admin', admin_role
                )

                return user_role
        except Exception as e:
            logger.warning(f"⚠️ Error getting admin user role: {e}")
            return None

    async def record_metadata(
        self,
        user_email: str,
        original_filename: str,
        file_display_name: str,
        file_ext: str,
        gemini_file_name: str,
        file_size: int,
        sha256_hash: str,
        final_state: str,
        gemini_processed_at: Any,
        mime_type: str,
        file_search_metadata: Optional[Dict[str, Any]] = None,
        char_count: int = 0,
        user_role_id: Optional[int] = None
    ) -> Optional[int]:
        """Record file metadata to database. Returns: file_id or None on failure"""
        try:
            # Use provided user_role_id or look it up from database
            if not user_role_id:
                user_role_id = await self.get_admin_user_role_id(user_email)

            query = """INSERT INTO file_uploads
                       (user_role_id, original_filename, display_name, file_extension,
                        mime_type, file_size, sha256_hash, gemini_file_name, processing_status,
                        gemini_processed_at, metadata, char_count, created_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW())
                       RETURNING id"""

            params = [
                user_role_id,
                original_filename,
                file_display_name,
                file_ext,
                mime_type,
                file_size,
                sha256_hash,
                gemini_file_name,
                final_state,
                gemini_processed_at,
                json.dumps(file_search_metadata) if file_search_metadata else None,
                char_count
            ]

            async with get_db_connection() as conn:
                file_id = await conn.fetchval(query, *params)
                logger.info(f"✅ Recorded metadata for {original_filename}, DB ID: {file_id}")
                return file_id
        except Exception as e:
            logger.error(f"❌ Error recording metadata: {e}")
            raise
