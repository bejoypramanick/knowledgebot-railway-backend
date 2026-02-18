"""
File DAO for Celery File Processing Worker
Handles database operations for file management
"""
from typing import Dict, List, Any, Optional
import json
from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("file_dao", "celery-file-worker")

class FileDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get file record by ID."""
        query = "SELECT * FROM file_uploads WHERE id = $1::text"
        params = {"file_id": file_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, file_id)
                logger.log_db_query(query, params, result)
                return dict(result) if result else None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def update_file_status(self, file_id: str, status: str, error_message: str = None):
        """Update file processing status."""
        query = """
            UPDATE file_uploads 
            SET processing_status = $1::text, error_message = $2::text, updated_at = NOW() 
            WHERE id = $3::int
        """
        params = [status, error_message, file_id]
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, status, error_message, file_id)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def get_files_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Get files by processing status."""
        query = "SELECT * FROM file_uploads WHERE processing_status = $1::text ORDER BY created_at DESC"
        params = {"status": status}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetch(query, status)
                logger.log_db_query(query, params, result)
                return [dict(row) for row in result] if result else []
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return []

    async def delete_file_record(self, file_id: str):
        """Delete a file record from database."""
        query = "DELETE FROM file_uploads WHERE id = $1::text"
        params = {"file_id": file_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, file_id)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise
