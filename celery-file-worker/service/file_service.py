"""
File Service for Celery File Processing Worker
Handles business logic for file processing operations
"""
import asyncio
import os
from typing import Dict, List, Any, Optional
from dao.file_dao import FileDAO
from shared.otel_logger import get_otel_logger
from shared.file_metrics import calculate_metrics

logger = get_otel_logger("file_service", "celery-file-worker")

class FileService:
    def __init__(self):
        self.file_dao = FileDAO()

    async def get_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get file by ID."""
        return await self.file_dao.get_file_by_id(file_id)

    async def update_file_status(self, file_id: str, status: str, error_message: str = None):
        """Update file processing status."""
        try:
            await self.file_dao.update_file_status(file_id, status, error_message)
            logger.info(f"✅ Updated file {file_id} status to {status}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to update file {file_id} status: {e}")
            return False

    async def get_files_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Get files by processing status."""
        return await self.file_dao.get_files_by_status(status)

    async def delete_file_record(self, file_id: str):
        """Delete file record."""
        try:
            await self.file_dao.delete_file_record(file_id)
            logger.info(f"✅ Deleted file record {file_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Failed to delete file record {file_id}: {e}")
            return False

    async def create_file_record(self, file_data: Dict[str, Any]) -> Optional[str]:
        """Create new file record."""
        try:
            file_id = await self.file_dao.insert_file_record(file_data)
            if file_id:
                logger.info(f"✅ Created file record {file_id}")
                return file_id
            else:
                logger.error("❌ Failed to create file record")
                return None
        except Exception as e:
            logger.error(f"❌ Error creating file record: {e}")
            return None

    async def is_task_cancelled(self, celery_task_id: str) -> bool:
        """Check if task has been marked for cancellation via Redis"""
        if not celery_task_id:
            return False

        try:
            import redis as redis_lib
            # Use FILE_REDIS_URL (DB 0) for file tasks
            redis_url = os.getenv('FILE_REDIS_URL', 'redis://localhost:6379/0')

            try:
                redis_conn = redis_lib.from_url(redis_url, socket_connect_timeout=2)
                cancelled_key = f"task_cancelled:{celery_task_id}"
                result = redis_conn.exists(cancelled_key)
                redis_conn.close()
                return bool(result)
            except redis_lib.ConnectionError as conn_err:
                # Redis not available - not critical, just skip cancellation check
                # This is common in local development without Redis
                logger.debug(f"ℹ️ Redis unavailable for cancellation check (this is OK): {redis_url}")
                return False
        except Exception as e:
            logger.debug(f"ℹ️ Skipping cancellation check: {e}")
            return False

    async def handle_duplicate_check(self, original_filename: str, replace_existing: bool = False, exclude_file_id: str = None) -> Dict[str, Any]:
        """
        Check for duplicate files by filename.
        Returns: {"allow": bool, "reason": str, "detail": str}
        
        Args:
            original_filename: Name of the file to check
            replace_existing: Whether to allow replacing existing files
            exclude_file_id: File ID to exclude from duplicate check (typically the current file being processed)
        """
        try:
            # Check if file with same name exists
            duplicate = await self.check_duplicate_file(original_filename, exclude_file_id)

            if duplicate:
                if replace_existing:
                    logger.info(f"🔄 Replacing existing duplicate: {original_filename}")
                    return {"allow": True, "reason": "replaced", "detail": "File will replace existing duplicate"}
                else:
                    logger.warning(f"⚠️ Duplicate file detected: {original_filename}")
                    return {"allow": False, "reason": "duplicate", "detail": f"File with same name already exists"}

            return {"allow": True, "reason": "new", "detail": "File is new"}
        except Exception as e:
            logger.error(f"❌ Error checking duplicates: {e}")
            raise

    async def check_duplicate_file(self, original_filename: str, exclude_file_id: str = None) -> Optional[Dict[str, Any]]:
        """Check if file with same name exists in database (only active files)."""
        from dao.fileupload_dao import FileUploadDAO
        dao = FileUploadDAO()
        return await dao.check_duplicate_file(original_filename, exclude_file_id)

    async def get_admin_user_role_id(self, user_email: str = None) -> Optional[str]:
        """Get admin user role ID from database."""
        from dao.fileupload_dao import FileUploadDAO
        dao = FileUploadDAO()
        return await dao.get_admin_user_role_id(user_email)

    async def delete_existing_file_record(self, file_id: str) -> bool:
        """Delete a file record from the database."""
        try:
            await self.delete_file_record(file_id)
            logger.info(f"✅ Deleted file record: {file_id}")
            return True
        except Exception as e:
            logger.error(f"❌ Error deleting file record: {e}")
            return False

    async def record_metadata(
        self,
        user_email: str,
        original_filename: str,
        file_display_name: str,
        file_ext: str,
        uploaded_file: Any,
        file_size: int,
        sha256_hash: str,
        final_state: str,
        gemini_processed_at: Any,
        mime_type: str,
        file_search_metadata: Optional[Dict[str, Any]] = None,
        char_count: int = 0,
        user_role_id: str = None
    ) -> Optional[str]:
        """Record file metadata to database. Returns: file_id or None on failure"""
        from dao.fileupload_dao import FileUploadDAO
        dao = FileUploadDAO()
        return await dao.record_metadata(
            user_email=user_email,
            original_filename=original_filename,
            file_display_name=file_display_name,
            file_ext=file_ext,
            gemini_file_name=uploaded_file.name,
            file_size=file_size,
            sha256_hash=sha256_hash,
            final_state=final_state,
            gemini_processed_at=gemini_processed_at,
            mime_type=mime_type,
            file_search_metadata=file_search_metadata,
            char_count=char_count,
            user_role_id=user_role_id
        )
