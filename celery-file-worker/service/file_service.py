"""
File Service for Celery File Processing Worker
Handles business logic for file processing operations
"""
import asyncio
import os
import json
from typing import Dict, List, Any, Optional
from ..dao.file_dao import FileDAO
from shared.otel_logger import get_otel_logger

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
            redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
            redis_conn = redis_lib.from_url(redis_url)

            cancelled_key = f"task_cancelled:{celery_task_id}"
            result = redis_conn.exists(cancelled_key)
            redis_conn.close()

            return bool(result)
        except Exception as e:
            logger.warning(f"⚠️ Error checking cancellation status: {e}")
            return False

    async def handle_duplicate_check(self, sha256_hash: str, original_filename: str, replace_existing: bool = False) -> Dict[str, Any]:
        """
        Check for duplicate files by hash.
        Returns: {"allow": bool, "reason": str, "detail": str}
        """
        try:
            # Check if file with same hash exists
            duplicate = await self.check_duplicate_file(sha256_hash)

            if duplicate:
                if replace_existing:
                    logger.info(f"🔄 Replacing existing duplicate: {original_filename}")
                    return {"allow": True, "reason": "replaced", "detail": "File will replace existing duplicate"}
                else:
                    logger.warning(f"⚠️ Duplicate file detected: {original_filename}")
                    return {"allow": False, "reason": "duplicate", "detail": f"File with same content already exists"}

            return {"allow": True, "reason": "new", "detail": "File is new"}
        except Exception as e:
            logger.error(f"❌ Error checking duplicates: {e}")
            raise

    async def check_duplicate_file(self, sha256_hash: str) -> Optional[Dict[str, Any]]:
        """Check if file with same hash exists in database."""
        try:
            from shared.db import get_db_connection

            async with get_db_connection() as conn:
                record = await conn.fetchrow(
                    "SELECT id, original_filename FROM file_uploads WHERE sha256_hash = $1 LIMIT 1",
                    sha256_hash
                )
                return record
        except Exception as e:
            logger.error(f"❌ Error checking duplicate: {e}")
            return None

    async def get_admin_user_role_id(self, user_email: str = None) -> Optional[str]:
        """Get admin user role ID from database."""
        try:
            from shared.db import get_db_connection

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
        file_search_metadata: Optional[Dict[str, Any]] = None
    ) -> Optional[int]:
        """
        Record file metadata to database.
        Returns: file_id or None on failure
        """
        try:
            from shared.db import get_db_connection

            # Get admin user role ID
            user_role_id = await self.get_admin_user_role_id(user_email)

            async with get_db_connection() as conn:
                file_id = await conn.fetchval(
                    """INSERT INTO file_uploads
                       (user_role_id, original_filename, display_name, file_extension,
                        mime_type, file_size, sha256_hash, gemini_file_name, processing_status,
                        gemini_processed_at, metadata, created_at)
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW())
                       RETURNING id""",
                    user_role_id,
                    original_filename,
                    file_display_name,
                    file_ext,
                    mime_type,
                    file_size,
                    sha256_hash,
                    uploaded_file.name,
                    final_state,
                    gemini_processed_at,
                    json.dumps(file_search_metadata) if file_search_metadata else None
                )

                logger.info(f"✅ Recorded metadata for {original_filename}, DB ID: {file_id}")
                return file_id
        except Exception as e:
            logger.error(f"❌ Error recording metadata: {e}")
            raise
