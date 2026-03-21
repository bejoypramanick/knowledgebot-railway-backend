"""
File DAO for Celery File Processing Worker
Handles database operations for file management
"""
from typing import Dict, List, Any, Optional
import json
from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("file_dao", "celery-file-worker")

class FileDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get file record by ID."""
        query = "SELECT * FROM file_uploads WHERE id = :file_id"
        params = {"file_id": file_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = (await session.execute(text(query), params)).fetchone()
                logger.log_db_query(query, params, result)
                return dict(result._mapping) if result else None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def update_file_status(self, file_id: str, status: str, error_message: str = None):
        """Update file processing status."""
        query = """
            UPDATE file_uploads
            SET processing_status = :status, error_message = :error_message, updated_at = NOW()
            WHERE id = :file_id
        """
        params = {"status": status, "error_message": error_message, "file_id": file_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, "UPDATE 1")
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def get_files_by_status(self, status: str) -> List[Dict[str, Any]]:
        """Get files by processing status."""
        query = "SELECT * FROM file_uploads WHERE processing_status = :status ORDER BY id DESC"
        params = {"status": status}
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                rows = result.fetchall()
                logger.log_db_query(query, params, rows)
                return [dict(row._mapping) for row in rows] if rows else []
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return []

    async def insert_file_record(self, record_data: Dict[str, Any]) -> Optional[str]:
        """Insert new file metadata record."""
        query = """
            INSERT INTO file_uploads (
                user_role_id, original_filename, display_name, file_size,
                mime_type, processing_status, gemini_file_name, gemini_file_uri,
                gemini_state, sha256_hash,
                metadata, created_at
            ) VALUES (
                :user_role_id, :original_filename, :display_name, :file_size,
                :mime_type, :processing_status, :gemini_file_name, :gemini_file_uri,
                :gemini_state, :sha256_hash,
                CAST(:metadata AS jsonb), NOW()
            ) RETURNING id
        """
        params = {
            "user_role_id": record_data.get('user_role_id') or record_data.get('user_id'),
            "original_filename": record_data.get('original_filename'),
            "display_name": record_data.get('file_display_name') or record_data.get('display_name'),
            "file_size": record_data.get('size_bytes') or record_data.get('file_size'),
            "mime_type": record_data.get('mime_type'),
            "processing_status": record_data.get('processing_status'),
            "gemini_file_name": record_data.get('gemini_file_name'),
            "gemini_file_uri": record_data.get('gemini_file_uri'),
            "gemini_state": record_data.get('gemini_state'),
            "sha256_hash": record_data.get('sha256_hash'),
            "metadata": record_data.get('file_search_metadata') or record_data.get('metadata', '{}'),
        }
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = (await session.execute(text(query), params)).scalar()
                logger.log_db_query(query, params, result)
                await session.commit()
                return str(result) if result else None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def delete_file_record(self, file_id: str):
        """Delete a file record from database."""
        query = "DELETE FROM file_uploads WHERE id = :file_id"
        params = {"file_id": file_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, "DELETE 1")
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise
