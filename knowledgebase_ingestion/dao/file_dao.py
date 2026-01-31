"""
File Data Access Object for Knowledgebase Ingestion
Handles database operations for file management
"""
from typing import Any, Dict, List, Optional

import logging

logger = logging.getLogger("file_dao")

class FileDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_user_by_email(self, email: str) -> Optional[str]:
        """Get user identifier - delegates to UserDAO for user table access."""
        try:
            from .user_dao import UserDAO
            user_dao = UserDAO()
            
            # Check if user exists in admins or human_agents tables
            roles = await user_dao.get_user_roles(email)
            if roles:
                return email
            return None
        except Exception as e:
            logger.error(f"Error checking user tables for email {email}: {e}")
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
        try:
            async with get_db_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO api_usage_log 
                    (user_id, provider, model, prompt_tokens, completion_tokens, total_tokens, api_call_type, request_metadata, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, NOW())
                    """,
                    user_id, provider, model, prompt_tokens, completion_tokens, total_tokens, api_call_type,
                    json.dumps(request_metadata) if request_metadata else None
                )
        except Exception as e:
            logger.exception("Failed to record API usage: %s", e)

    async def find_duplicate_by_hash(self, sha256_hash: str) -> Optional[Dict[str, Any]]:
        """Find a file by its SHA256 hash."""
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(
                    "SELECT * FROM file_uploads WHERE sha256_hash = $1",
                    sha256_hash
                )
                return dict(result) if result else None
        except Exception as e:
            logger.error(f"Error finding duplicate by hash: {e}")
            return None

    async def find_duplicate_by_name(self, original_filename: str) -> Optional[Dict[str, Any]]:
        """Find a file by its original filename."""
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(
                    "SELECT * FROM file_uploads WHERE original_filename = $1",
                    original_filename
                )
                return dict(result) if result else None
        except Exception as e:
            logger.error(f"Error finding duplicate by name: {e}")
            return None

    async def delete_file_record(self, db_id: str):
        """Delete a file record from the database."""
        try:
            async with get_db_connection() as conn:
                await conn.execute(
                    "DELETE FROM file_uploads WHERE id = $1",
                    db_id
                )
        except Exception as e:
            logger.error(f"Error deleting file record: {e}")

    async def insert_file_record(self, record_data: Dict[str, Any]) -> str:
        """Insert new file metadata record."""
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(
                    """
                    INSERT INTO file_uploads 
                    (user_id, original_filename, file_size, mime_type, gemini_file_id, 
                     gemini_state, gemini_display_name, version, sha256_hash, upload_timestamp)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                    RETURNING id
                    """,
                    record_data['user_id'],
                    record_data['original_filename'],
                    record_data['file_size'],
                    record_data['mime_type'],
                    record_data['gemini_file_id'],
                    record_data['gemini_state'],
                    record_data['gemini_display_name'],
                    record_data['version'],
                    record_data['sha256_hash']
                )
                return result['id']
        except Exception as e:
            logger.error(f"Error inserting file record: {e}")
            raise

    async def record_metric(self, metric_data: Dict[str, Any]):
        """Log a metric record."""
        try:
            async with get_db_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO metrics_log 
                    (metric_type, metric_value, metadata, created_at)
                    VALUES ($1, $2, $3, NOW())
                    """,
                    metric_data['metric_type'],
                    metric_data['metric_value'],
                    json.dumps(metric_data['metadata'])
                )
        except Exception as e:
            logger.error(f"Error recording metric: {e}")

    async def get_active_files_count(self) -> int:
        """Get count of active files."""
        try:
            async with get_db_connection() as conn:
                result = await conn.fetchrow(
                    "SELECT COUNT(*) FROM file_uploads WHERE gemini_state = 'ACTIVE'"
                )
                return result['count'] if result else 0
        except Exception as e:
            logger.error(f"Error getting active files count: {e}")
            return 0

    async def get_recent_files(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent uploaded files."""
        try:
            async with get_db_connection() as conn:
                results = await conn.fetch(
                    """
                    SELECT original_filename, gemini_display_name, upload_timestamp, file_size
                    FROM file_uploads 
                    WHERE gemini_state = 'ACTIVE'
                    ORDER BY upload_timestamp DESC
                    LIMIT $1
                    """,
                    limit
                )
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Error getting recent files: {e}")
            return []

    async def get_files(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get active files."""
        try:
            async with get_db_connection() as conn:
                results = await conn.fetch(
                    """
                    SELECT id, original_filename, gemini_display_name, upload_timestamp, file_size
                    FROM file_uploads 
                    WHERE gemini_state = 'ACTIVE'
                    ORDER BY upload_timestamp DESC
                    LIMIT $1
                    """,
                    limit
                )
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Error getting files: {e}")
            return []

    async def get_recent_metrics(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent metrics"""
        try:
            async with get_db_connection() as conn:
                results = await conn.fetch(
                    """
                    SELECT metric_type, metric_value, metadata, created_at
                    FROM metrics_log
                    ORDER BY created_at DESC
                    LIMIT $1
                    """,
                    limit
                )
                return [dict(row) for row in results]
        except Exception as e:
            logger.error(f"Error getting recent metrics: {e}")
            return []

    async def find_file_by_id(self, file_id: str, table_name: str):
        """Find file by ID in specified table"""
        try:
            async with get_db_connection() as conn:
                if table_name == 'file_uploads':
                    result = await conn.fetchrow(
                        "SELECT * FROM file_uploads WHERE id = $1",
                        file_id
                    )
                    return dict(result) if result else None
                else:
                    logger.warning(f"Unknown table name: {table_name}")
                    return None
        except Exception as e:
            logger.error(f"Error finding file by ID: {e}")
            return None

    async def delete_file_by_id(self, file_id: str, table_name: str):
        """Delete file by ID from specified table"""
        try:
            async with get_db_connection() as conn:
                query = f"DELETE FROM {table_name} WHERE id = $1"
                await conn.execute(query, file_id)
        except Exception as e:
            logger.error(f"Error deleting file by ID: {e}")
