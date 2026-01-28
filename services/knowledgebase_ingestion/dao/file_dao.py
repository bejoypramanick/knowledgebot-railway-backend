import logging
import json
from typing import Optional, Dict, Any, List
from shared import db

logger = logging.getLogger(__name__)

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
