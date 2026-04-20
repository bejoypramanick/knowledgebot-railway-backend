"""
File Upload Data Access Object for Celery File Worker
Handles database operations for file uploads - mirrors web worker pattern
"""

from typing import Any, Dict, Optional
import json

from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("fileupload_dao", "celery-file-worker")


class FileUploadDAO:
    def __init__(self):
        pass

    async def update_file_status(
        self, file_id: str, status: str, error_message: str = None
    ) -> bool:
        """Update file processing status."""
        logger.info(
            f"💾 [FILE_UPDATE_STATUS] Updating file {file_id} status to: {status}"
        )

        query = """
            UPDATE file_uploads
            SET processing_status = :status, error_message = :error_message, updated_at = NOW()
            WHERE id = :file_id AND processing_status != 'deleted'
        """
        params = {"file_id": file_id, "status": status, "error_message": error_message}

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, "UPDATE 1")

                if result.rowcount > 0:
                    logger.info(
                        f"✅ [FILE_UPDATE_STATUS_SUCCESS] Status updated to: {status}"
                    )
                    return True
                else:
                    logger.warning(
                        f"⚠️  [FILE_UPDATE_STATUS_NO_ROWS] No rows updated (file_id {file_id} may not exist)"
                    )
                    return False
        except Exception as e:
            logger.error(
                f"❌ [FILE_UPDATE_STATUS_ERROR] Failed to update file status: {e}"
            )
            logger.log_db_query(query, params, error=e)
            return False

    async def update_file_with_processing_data(
        self,
        file_id: str,
        storage_document_name: str,
        storage_document_uri: str,
        storage_backend_state: str,
        file_size: int,
        char_count: int,
        sha256_hash: str,
        metadata: Dict[str, Any],
        processed_by_extractor: bool = False,
        extractor_processing_time_ms: int = None,
        extractor_images_extracted: int = 0,
        extractor_images_with_ocr: int = 0,
        original_file_extension: str = None,
        original_mime_type: str = None,
        processed_content_s3_key: str = None,
        total_pages: int = 0,
    ) -> bool:
        """
        Update file record with all processing data after successful upload.
        Mirrors the web worker's update_website_with_page_data pattern.

        Returns: True on success, False on failure
        """
        logger.info(
            f"💾 [UPDATE_FILE_DATA] Updating file {file_id} with processing data"
        )
        logger.info(f"   Storage Document: {storage_document_name}")
        logger.info(f"   File Size: {file_size:,} bytes")
        logger.info(f"   Char Count: {char_count:,}")
        logger.info(f"   Processed by Extractor: {processed_by_extractor}")

        query = """
            UPDATE file_uploads
            SET storage_document_name = :storage_document_name,
                storage_document_uri = :storage_document_uri,
                storage_backend_state = :storage_backend_state,
                file_size = :file_size,
                char_count = :char_count,
                sha256_hash = :sha256_hash,
                metadata = CAST(:metadata AS jsonb),
                processed_by_extractor = :processed_by_extractor,
                extractor_processing_time_ms = :extractor_processing_time_ms,
                extractor_images_extracted = :extractor_images_extracted,
                extractor_images_with_ocr = :extractor_images_with_ocr,
                file_extension = :original_file_extension,
                mime_type = :original_mime_type,
                processed_content_s3_key = :processed_content_s3_key,
                total_pages = :total_pages,
                processing_status = 'completed',
                completed_at = COALESCE(completed_at, NOW()),
                updated_at = NOW()
            WHERE id = :file_id AND processing_status != 'deleted'
        """

        params = {
            "storage_document_name": storage_document_name,
            "storage_document_uri": storage_document_uri,
            "storage_backend_state": storage_backend_state,
            "file_size": file_size,
            "char_count": char_count,
            "sha256_hash": sha256_hash,
            "metadata": json.dumps(metadata),
            "processed_by_extractor": processed_by_extractor,
            "extractor_processing_time_ms": extractor_processing_time_ms,
            "extractor_images_extracted": extractor_images_extracted,
            "extractor_images_with_ocr": extractor_images_with_ocr,
            "original_file_extension": original_file_extension,
            "original_mime_type": original_mime_type,
            "processed_content_s3_key": processed_content_s3_key,
            "total_pages": total_pages,
            "file_id": file_id,
        }

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                await session.execute(text(query), params)

                # Update file_size from document_chunks AFTER chunks are stored
                size_query = text("""
                    UPDATE file_uploads
                    SET file_size = (
                        SELECT COALESCE(SUM(pg_column_size(dc.content)), 0)::bigint
                        FROM document_chunks dc
                        WHERE dc.document_id = :file_id AND dc.document_type = 'file'
                    )
                    WHERE id = :file_id
                """)
                await session.execute(size_query, {"file_id": file_id})
                await session.commit()

                logger.info(
                    f"✅ [UPDATE_FILE_DATA_SUCCESS] File record updated and marked as completed"
                )
                logger.log_db_query(query, params, "UPDATE succeeded")
                return True
        except Exception as e:
            logger.error(f"❌ [UPDATE_FILE_DATA_ERROR] Failed to update file: {e}")
            logger.error(f"   File ID: {file_id}")
            import traceback

            logger.error(f"   Traceback: {traceback.format_exc()}")
            logger.log_db_query(query, params, error=e)
            return False

    async def get_file_by_task_id(
        self, celery_task_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get file record by celery_task_id."""
        query = """
            SELECT id, user_role_id, original_filename, display_name, file_extension,
                   s3_key, file_size, mime_type, sha256_hash, processing_status,
                   celery_task_id, created_at, updated_at
            FROM file_uploads
            WHERE celery_task_id = :celery_task_id
        """

        try:
            params = {"celery_task_id": celery_task_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = (await session.execute(text(query), params)).fetchone()
                logger.log_db_query(query, params, result)

                if result:
                    return dict(result._mapping)
                return None
        except Exception as e:
            logger.error(f"❌ Error getting file by task_id: {e}")
            logger.log_db_query(query, {"celery_task_id": celery_task_id}, error=e)
            return None

    async def get_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get file record by file ID."""
        query = """
            SELECT id, user_role_id, original_filename, display_name,
                   s3_key, file_size, mime_type, processing_status, sha256_hash
            FROM file_uploads
            WHERE id = :file_id
        """

        try:
            params = {"file_id": file_id}
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = (await session.execute(text(query), params)).fetchone()
                logger.log_db_query(query, params, result)

                if result:
                    logger.info(f"✅ [DB_QUERY] File found: {result.original_filename}")
                    return dict(result._mapping)
                else:
                    logger.error(f"❌ [DB_QUERY] No file found for file_id: {file_id}")
                    return None
        except Exception as e:
            logger.error(f"❌ Error getting file by ID: {e}")
            logger.log_db_query(query, {"file_id": file_id}, error=e)
            return None

    async def check_duplicate_file(
        self, original_filename: str, exclude_file_id: Optional[str] = None
    ) -> Optional[Dict[str, Any]]:
        """Check if file with same name exists in database (only active files)."""
        try:
            async with get_db_session() as session:
                # First, log ALL files with this name to debug
                all_query = "SELECT id, original_filename, processing_status FROM file_uploads WHERE original_filename = :original_filename ORDER BY id DESC"
                all_files_result = await session.execute(
                    text(all_query), {"original_filename": original_filename}
                )
                all_files = all_files_result.fetchall()
                logger.info(
                    f"🔍 [DUPLICATE_CHECK_ALL] Found {len(all_files)} total files with name '{original_filename}':"
                )
                for f in all_files:
                    logger.info(f"   - ID={f.id}, status={f.processing_status}")

                # Only check active files (exclude failed, deleted, cancelled)
                # Also exclude the current file being processed
                if exclude_file_id:
                    query = "SELECT id, original_filename, processing_status FROM file_uploads WHERE original_filename = :original_filename AND id != :exclude_file_id AND processing_status IN ('pending', 'processing', 'queued', 'completed') LIMIT 1"
                    record = (
                        await session.execute(
                            text(query),
                            {
                                "original_filename": original_filename,
                                "exclude_file_id": exclude_file_id,
                            },
                        )
                    ).fetchone()
                    logger.info(
                        f"🔍 [DUPLICATE_CHECK] Excluding current file ID={exclude_file_id} from check"
                    )
                else:
                    query = "SELECT id, original_filename, processing_status FROM file_uploads WHERE original_filename = :original_filename AND processing_status IN ('pending', 'processing', 'queued', 'completed') LIMIT 1"
                    record = (
                        await session.execute(
                            text(query), {"original_filename": original_filename}
                        )
                    ).fetchone()

                if record:
                    logger.warning(
                        f"🔍 [DUPLICATE_CHECK] Found ACTIVE duplicate: ID={record.id}, filename={record.original_filename}, status={record.processing_status}"
                    )
                else:
                    logger.info(
                        f"🔍 [DUPLICATE_CHECK] No active duplicate found for: {original_filename}"
                    )

                return dict(record._mapping) if record else None
        except Exception as e:
            logger.error(f"❌ Error checking duplicate: {e}")
            return None

    async def get_admin_user_role_id(
        self, user_email: Optional[str] = None
    ) -> Optional[str]:
        """Get admin user role ID from database."""
        try:
            async with get_db_session() as session:
                # Get admin role first
                admin_role = (
                    await session.execute(
                        text("SELECT id FROM roles WHERE role_name = 'admin' LIMIT 1")
                    )
                ).scalar()

                if not admin_role:
                    logger.warning("⚠️ Admin role not found in database")
                    return None

                # Get user role mapping for this email
                user_role = (
                    await session.execute(
                        text("""
                    SELECT urm.user_role_id FROM user_role_mapping urm
                    JOIN users u ON urm.user_id = u.id
                    WHERE u.email = :email AND urm.role_id = :role_id LIMIT 1
                """),
                        {"email": user_email or "admin", "role_id": admin_role},
                    )
                ).scalar()

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
        storage_document_name: str,
        file_size: int,
        sha256_hash: str,
        final_state: str,
        storage_processed_at: Any,
        mime_type: str,
        storage_metadata: Optional[Dict[str, Any]] = None,
        char_count: int = 0,
        user_role_id: Optional[str] = None,
    ) -> Optional[str]:
        """Record file metadata to database. Returns: file_id or None on failure"""
        try:
            # Use provided user_role_id or look it up from database
            if not user_role_id:
                user_role_id = await self.get_admin_user_role_id(user_email)

            query = """INSERT INTO file_uploads
                       (user_role_id, original_filename, display_name, file_extension,
                        mime_type, file_size, sha256_hash, storage_document_name, processing_status,
                        gemini_processed_at, metadata, char_count, created_at)
                       VALUES (:user_role_id, :original_filename, :display_name, :file_extension,
                        :mime_type, :file_size, :sha256_hash, :storage_document_name, :processing_status,
                        :storage_processed_at, :metadata, :char_count, NOW())
                       RETURNING id"""

            params = {
                "user_role_id": user_role_id,
                "original_filename": original_filename,
                "display_name": file_display_name,
                "file_extension": file_ext,
                "mime_type": mime_type,
                "file_size": file_size,
                "sha256_hash": sha256_hash,
                "storage_document_name": storage_document_name,
                "processing_status": final_state,
                "storage_processed_at": storage_processed_at,
                "metadata": json.dumps(storage_metadata) if storage_metadata else None,
                "char_count": char_count,
            }

            async with get_db_session() as session:
                file_id = (await session.execute(text(query), params)).scalar()
                await session.commit()
                logger.info(
                    f"✅ Recorded metadata for {original_filename}, DB ID: {file_id}"
                )
                return file_id
        except Exception as e:
            logger.error(f"❌ Error recording metadata: {e}")
            raise

    async def get_file_metadata_for_deletion(
        self, file_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get file metadata for deletion operations (from file_uploads table)."""
        query = "SELECT storage_document_name, original_filename, metadata FROM file_uploads WHERE id = :file_id"
        try:
            async with get_db_session() as session:
                record = (
                    await session.execute(text(query), {"file_id": file_id})
                ).fetchone()
                return dict(record._mapping) if record else None
        except Exception as e:
            logger.error(f"❌ Error getting file metadata for deletion: {e}")
            return None
