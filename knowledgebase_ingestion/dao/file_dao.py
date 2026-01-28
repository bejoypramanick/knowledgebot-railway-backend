from shared.logging_config import get_railway_logger
import logging
import json
from typing import Optional, Dict, Any, List
from shared import db

logger = get_railway_logger(__name__)

class FileDAO:
    def __init__(self, database):
        self.db = database

    async def get_user_by_email(self, email: str) -> Optional[str]:
        """Get user identifier from admins or human_agents table."""
        if not self.db:
            return None
        
        try:
            # Check if user exists in admins table
            admin_user = await self.db.fetchrow(
                "SELECT email FROM admins WHERE email = $1",
                email
            )
            if admin_user:
                return email
            
            # Check if user exists in human_agents table
            agent_user = await self.db.fetchrow(
                "SELECT email FROM human_agents WHERE email = $1",
                email
            )
            if agent_user:
                return email
            
            return None
        except Exception as e:
            logger.error(f"Error checking user tables for email {email}: {e}")
            return None

    async def record_api_usage(
        self,
        user_id: Optional[str],
        provider: str,
        endpoint: str,
        method: str,
        status_code: int,
        req_size: int,
        res_size: int,
        duration_ms: int,
        metadata: Dict[str, Any]
    ):
        """Record API usage to the database."""
        if not self.db:
            return

        try:
            await self.db.execute(
                """
                INSERT INTO api_usage (
                    api_provider, api_endpoint, http_method,
                    request_size_bytes, response_size_bytes, status_code,
                    user_email, duration_ms, metadata
                )
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """,
                provider, endpoint, method,
                req_size, res_size, status_code,
                user_id, duration_ms, json.dumps(metadata or {})
            )
        except Exception as e:
            logger.exception("Failed to record API usage: %s", e)

    async def find_duplicate_by_hash(self, sha256_hash: str) -> Optional[Dict[str, Any]]:
        """Find a file by its SHA256 hash."""
        if not self.db:
            return None
            
        return await self.db.fetchrow(
            """
            SELECT id, original_filename, display_name, sha256_hash, size_bytes, gemini_file_name,
                   COALESCE(version, 1) as version
            FROM file_uploads 
            WHERE sha256_hash = $1
            ORDER BY version DESC, created_at DESC
            LIMIT 1
            """,
            sha256_hash
        )

    async def find_duplicate_by_name(self, original_filename: str) -> Optional[Dict[str, Any]]:
        """Find a file by its original filename."""
        if not self.db:
            return None
            
        return await self.db.fetchrow(
            """
            SELECT id, original_filename, display_name, sha256_hash, size_bytes, gemini_file_name,
                   COALESCE(version, 1) as version
            FROM file_uploads 
            WHERE original_filename = $1
            ORDER BY version DESC, created_at DESC
            LIMIT 1
            """,
            original_filename
        )

    async def delete_file_record(self, db_id: str):
        """Delete a file record from the database."""
        if not self.db:
            return
            
        await self.db.execute(
            "DELETE FROM file_uploads WHERE id = $1",
            db_id
        )

    async def insert_file_record(self, record_data: Dict[str, Any]) -> str:
        """Insert new file metadata record."""
        if not self.db:
            return None

        return await self.db.fetchval(
            """
            INSERT INTO file_uploads (
                user_email, original_filename, display_name, file_extension,
                gemini_file_name, gemini_file_uri,
                mime_type, size_bytes, sha256_hash,
                gemini_upload_status, gemini_state,
                gemini_processed_at, expires_at, metadata, version
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, $13, $14, $15)
            RETURNING id
            """,
            record_data['user_id'],
            record_data['original_filename'],
            record_data['display_name'],
            record_data['file_ext'],
            record_data['gemini_file_name'],
            record_data['gemini_file_uri'],
            record_data['mime_type'],
            record_data['file_size'],
            record_data['sha256_hash'],
            record_data['status'],
            record_data['state'],
            record_data['processed_at'],
            record_data['expires_at'],
            json.dumps(record_data['metadata']),
            record_data['version']
        )

    async def record_metric(self, metric_data: Dict[str, Any]):
        """Log a metric record."""
        if not self.db:
            return
            
        await self.db.execute(
            """
            INSERT INTO metrics (metric_type, metric_name, value, unit, user_email, file_upload_id, metadata)
            VALUES ($1, $2, $3, $4, $5, $6, $7)
            """,
            metric_data['type'],
            metric_data['name'],
            metric_data['value'],
            metric_data['unit'],
            metric_data['user_id'],
            metric_data['file_id'],
            json.dumps(metric_data['metadata'])
        )

    async def get_active_files_count(self) -> int:
        """Get count of active files."""
        if not self.db:
            return 0
        
        return await self.db.fetchval(
            "SELECT COUNT(*) FROM file_uploads WHERE gemini_state = 'ACTIVE'"
        )

    async def get_recent_files(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent uploaded files."""
        if not self.db:
            return []
        
        return await self.db.fetch(
            """
            SELECT display_name, mime_type, size_bytes, uploaded_at
            FROM file_uploads
            WHERE gemini_state = 'ACTIVE'
            ORDER BY uploaded_at DESC
            LIMIT $1
            """,
            limit
        )

    async def get_files(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get active files."""
        if not self.db:
            return []
        
        return await self.db.fetch(
            """
            SELECT display_name, mime_type, size_bytes, uploaded_at
            FROM file_uploads
            WHERE gemini_state = 'ACTIVE'
            ORDER BY uploaded_at DESC
            LIMIT $1
            """,
            limit
        )

    async def get_recent_metrics(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent metrics"""
        try:
            return await self.get_recent_metrics(limit)
        except Exception as e:
            logger.error(f"Error getting recent metrics: {e}")
            return []

    async def find_file_by_id(self, file_id: str, table_name: str):
        """Find file by ID in specified table"""
        try:
            if table_name == 'file_uploads':
                return await self.fetchrow(
                    "SELECT gemini_file_name, original_filename, 'file_uploads' as table_name FROM file_uploads WHERE id = $1",
                    file_id
                )
            elif table_name == 'scraped_websites':
                return await self.fetchrow(
                    "SELECT gemini_file_name, original_url as original_filename, 'scraped_websites' as table_name FROM scraped_websites WHERE id = $1",
                    file_id
                )
            return None
        except Exception as e:
            logger.error(f"Error finding file by ID: {e}")
            return None

    async def delete_file_by_id(self, file_id: str, table_name: str):
        """Delete file by ID from specified table"""
        try:
            query = f"DELETE FROM {table_name} WHERE id = $1"
            await self.execute(query, file_id)
        except Exception as e:
            logger.error(f"Error deleting file by ID: {e}")
            raise
