"""
File Data Access Object for Knowledgebase Ingestion
Handles database operations for file management
"""
from typing import Any, Dict, List, Optional

from knowledgebase_ingestion.core.db import get_db_connection
from knowledgebase_ingestion.core.otel_logger import get_otel_logger

logger = get_otel_logger("file_dao", "knowledgebase-ingestion")

class FileDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_user_by_email(self, email: str) -> Optional[str]:
        """Get user identifier - check if user exists in users table."""
        try:
            query = "SELECT email FROM users WHERE email = $1"
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, email)
                logger.log_db_query(query, {"email": email}, result)
                return result if result else None
        except Exception as e:
            logger.error(f"Error checking user table for email {email}: {e}")
            return None

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
            async with get_db_connection() as conn:
                result = await conn.execute(query, *params)
                logger.log_db_query(query, params, result)
        except Exception as e:
            logger.log_db_query(query, params, error=e)

    async def find_duplicate_by_hash(self, sha256_hash: str) -> Optional[Dict[str, Any]]:
        """Find a file by its SHA256 hash."""
        query = "SELECT * FROM file_uploads WHERE sha256_hash = $1"
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, sha256_hash)
                logger.log_db_query(query, {"sha256_hash": sha256_hash}, result)
                return dict(result) if result else None
        except Exception as e:
            logger.log_db_query(query, {"sha256_hash": sha256_hash}, error=e)
            return None

    async def find_duplicate_by_name(self, original_filename: str) -> Optional[Dict[str, Any]]:
        """Find a file by its original filename."""
        query = "SELECT * FROM file_uploads WHERE original_filename = $1"
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, original_filename)
                logger.log_db_query(query, {"original_filename": original_filename}, result)
                return dict(result) if result else None
        except Exception as e:
            logger.log_db_query(query, {"original_filename": original_filename}, error=e)
            return None

    async def delete_file_record(self, db_id: str):
        """Delete a file record from the database."""
        query = "DELETE FROM file_uploads WHERE id = $1"
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, db_id)
                logger.log_db_query(query, {"db_id": db_id}, result)
        except Exception as e:
            logger.log_db_query(query, {"db_id": db_id}, error=e)

    async def insert_file_record(self, record_data: Dict[str, Any]) -> str:
        """Insert new file metadata record."""
        query = """
            INSERT INTO file_uploads 
            (user_role_id, original_filename, file_size, mime_type, gemini_file_id, 
             gemini_state, gemini_display_name, version, sha256_hash, upload_timestamp)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
            RETURNING id
        """
        params = [
            record_data.get('user_role_id'),  # Updated to user_role_id
            record_data['original_filename'],
            record_data['file_size'],
            record_data['mime_type'],
            record_data['gemini_file_id'],
            record_data['gemini_state'],
            record_data['gemini_display_name'],
            record_data['version'],
            record_data['sha256_hash']
        ]
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, *params)
                logger.log_db_query(query, params, result)
                return result
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

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
            json.dumps(metric_data['metadata'])
        ]
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, *params)
                logger.log_db_query(query, params, result)
        except Exception as e:
            logger.log_db_query(query, params, error=e)

    async def get_active_files_count(self) -> int:
        """Get count of active files."""
        query = "SELECT COUNT(*) FROM file_uploads WHERE gemini_state = 'ACTIVE'"
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchval(query)
                logger.log_db_query(query, None, result)
                return result if result else 0
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return 0

    async def get_recent_files(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent uploaded files."""
        query = """
            SELECT original_filename, gemini_display_name, upload_timestamp, file_size
            FROM file_uploads 
            WHERE gemini_state = 'ACTIVE'
            ORDER BY upload_timestamp DESC
            LIMIT $1
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetch(query, limit)
                logger.log_db_query(query, {"limit": limit}, result)
                return [dict(row) for row in result]
        except Exception as e:
            logger.log_db_query(query, {"limit": limit}, error=e)
            return []

    async def get_files(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get active files."""
        query = """
            SELECT id, original_filename, gemini_display_name, upload_timestamp, file_size
            FROM file_uploads 
            WHERE gemini_state = 'ACTIVE'
            ORDER BY upload_timestamp DESC
            LIMIT $1
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetch(query, limit)
                logger.log_db_query(query, {"limit": limit}, result)
                return [dict(row) for row in result]
        except Exception as e:
            logger.log_db_query(query, {"limit": limit}, error=e)
            return []

    async def get_recent_metrics(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent metrics"""
        query = """
            SELECT metric_type, metric_value, metadata, created_at
            FROM metrics_log
            ORDER BY created_at DESC
            LIMIT $1
        """
        try:
            async with get_db_connection() as conn:
                result = await conn.fetch(query, limit)
                logger.log_db_query(query, {"limit": limit}, result)
                return [dict(row) for row in result]
        except Exception as e:
            logger.log_db_query(query, {"limit": limit}, error=e)
            return []

    async def find_file_by_id(self, file_id: str, table_name: str):
        """Find file by ID in specified table"""
        try:
            async with get_db_connection() as conn:
                if table_name == 'file_uploads':
                    query = "SELECT * FROM file_uploads WHERE id = $1"
                    result = await conn.fetchrow(query, file_id)
                    logger.log_db_query(query, {"file_id": file_id}, result)
                    return dict(result) if result else None
                else:
                    logger.warning(f"Unknown table name: {table_name}")
                    return None
        except Exception as e:
            logger.log_db_query("find_file_by_id", {"file_id": file_id, "table_name": table_name}, error=e)
            return None

    async def delete_file_by_id(self, file_id: str, table_name: str):
        """Delete file by ID from specified table"""
        try:
            async with get_db_connection() as conn:
                query = f"DELETE FROM {table_name} WHERE id = $1"
                result = await conn.execute(query, file_id)
                logger.log_db_query(query, {"file_id": file_id}, result)
        except Exception as e:
            logger.log_db_query(query, {"file_id": file_id}, error=e)
