"""
File Upload Data Access Object
Handles database operations for file uploads only
"""
from typing import Any, Dict, List, Optional
import json

from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("fileupload_dao", "knowledgebase-ingestion")

class FileUploadDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_user_by_email(self, email: str) -> Optional[str]:
        """Get user identifier - check if user exists in users table."""
        query = "SELECT email FROM users WHERE email = $1"
        params = {"email": email}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, email)
                logger.log_db_query(query, params, result)
                return result if result else None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def create_file_record(self, record_data: Dict[str, Any]) -> Optional[str]:
        """Insert new file metadata record."""
        query = """
            INSERT INTO file_uploads (
                user_id, original_filename, file_display_name, size_bytes, 
                mime_type, processing_status, gemini_file_name, gemini_file_uri, 
                gemini_state, gemini_processed_at, source, sha256_hash, 
                file_search_metadata, created_at
            ) VALUES (
                $1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW()
            ) RETURNING id
        """
        params = [
            record_data.get('user_id'),
            record_data.get('original_filename'),
            record_data.get('file_display_name'),
            record_data.get('size_bytes'),
            record_data.get('mime_type'),
            record_data.get('processing_status'),
            record_data.get('gemini_file_name'),
            record_data.get('gemini_file_uri'),
            record_data.get('gemini_state'),
            record_data.get('gemini_processed_at'),
            record_data.get('source'),
            record_data.get('sha256_hash'),
            record_data.get('file_search_metadata'),
        ]
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, *params)
                logger.log_db_query(query, params, result)
                return str(result) if result else None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def get_file_by_id(self, file_id: int) -> Optional[Dict[str, Any]]:
        """Get file record by ID."""
        query = """
            SELECT id, original_filename, processing_status, error_message, created_at, updated_at
            FROM file_uploads WHERE id = $1
        """
        params = {"file_id": file_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, file_id)
                logger.log_db_query(query, params, result)
                if result:
                    return {
                        "id": str(result['id']),
                        "original_filename": result['original_filename'],
                        "processing_status": result['processing_status'],
                        "error_message": result['error_message'],
                        "created_at": result['created_at'],
                        "updated_at": result['updated_at']
                    }
                return None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def get_all_files(self) -> List[Dict[str, Any]]:
        """Get all files with their status."""
        query = """
            SELECT id, original_filename, processing_status, error_message, created_at, updated_at
            FROM file_uploads
            ORDER BY updated_at DESC
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, result=result)
                return result
        except Exception as e:
            logger.log_db_query(query, error=e)
            return []

    async def get_pending_files(self) -> List[Dict[str, Any]]:
        """Get all files with pending or processing status."""
        query = """
            SELECT id, original_filename, processing_status, error_message, created_at, updated_at
            FROM file_uploads
            WHERE processing_status IN ('pending', 'processing')
            ORDER BY updated_at DESC
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, result=result)
                return result
        except Exception as e:
            logger.log_db_query(query, error=e)
            return []

    async def update_file_status(self, file_id: int, status: str, error_message: str = None) -> bool:
        """Update file processing status."""
        query = """
            UPDATE file_uploads 
            SET processing_status = $2, error_message = $3, updated_at = NOW()
            WHERE id = $1
        """
        params = [status, error_message, file_id]
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, status, error_message, file_id)
                logger.log_db_query(query, params, result)
                return result != "UPDATE 0"
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False

    async def cancel_files(self) -> int:
        """Cancel all pending/processing files."""
        query = """
            UPDATE file_uploads 
            SET processing_status = 'cancelled', updated_at = NOW()
            WHERE processing_status IN ('pending', 'processing')
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.execute(query)
                logger.log_db_query(query, result=result)
                return result
        except Exception as e:
            logger.log_db_query(query, error=e)
            return 0

    async def record_api_usage(
        self,
        user_id: Optional[str],
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        api_call_type: str,
        request_metadata: Optional[Dict[str, Any]] = None
    ):
        """Record API usage in the database."""
        query = """
            INSERT INTO api_usage_log 
            (user_id, provider, model, prompt_tokens, completion_tokens, total_tokens, api_call_type, request_metadata, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
        """
        params = [user_id, provider, model, prompt_tokens, completion_tokens, total_tokens, api_call_type,
                  json.dumps(request_metadata) if request_metadata else None]
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, *params)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def record_metric(self, metric_data: Dict[str, Any]):
        """Log a metric record."""
        query = """
            INSERT INTO metrics_log 
            (metric_type, metric_value, metadata, created_at)
            VALUES ($1, $2, $3, NOW())
        """
        params = [
            metric_data['metric_type'],
            metric_data['metric_value'],
            json.dumps(metric_data.get('metadata', {}))
        ]
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, *params)
                logger.log_db_query(query, params, result)
        except Exception as e:
            logger.log_db_query(query, params, error=e)
