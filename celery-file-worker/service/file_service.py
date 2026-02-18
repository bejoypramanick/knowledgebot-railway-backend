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
