from typing import Any, Dict, List, Optional

from shared.db import get_db_connection
from shared.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class ChatDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_session_metadata(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve metadata for a chat session."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchrow("""
                    SELECT file_search_store_id, cached_content_id, created_at, updated_at
                    FROM chat_sessions 
                    WHERE session_id = $1
                    ORDER BY created_at DESC
                    LIMIT 1
                """, session_id)
        except Exception as e:
            logger.error(f"Error getting session metadata: {e}")
            return None

    async def update_session_metadata(self, session_id: str, file_search_store_id: str = None, cached_content_id: str = None):
        """Update or insert session metadata."""
        try:
            async with get_db_connection() as conn:
                await conn.execute("""
                    INSERT INTO chat_sessions (session_id, file_search_store_id, cached_content_id, created_at, updated_at)
                    VALUES ($1, $2, $3, NOW(), NOW())
                    ON CONFLICT (session_id) 
                    DO UPDATE SET 
                        file_search_store_id = COALESCE(EXCLUDED.file_search_store_id, chat_sessions.file_search_store_id),
                        cached_content_id = COALESCE(EXCLUDED.cached_content_id, chat_sessions.cached_content_id),
                        updated_at = NOW()
                """, session_id, file_search_store_id, cached_content_id)
        except Exception as e:
            logger.error(f"Error updating session metadata: {e}")

    async def get_recent_files(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieve recent file uploads metadata."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetch("""
                    SELECT gemini_file_name, original_filename, display_name, mime_type, size_bytes, created_at
                    FROM file_uploads
                    WHERE gemini_file_name IS NOT NULL
                    ORDER BY created_at DESC
                    LIMIT $1
                """, limit)
        except Exception as e:
            logger.error(f"Error getting recent files: {e}")
            return []

    async def find_file_by_name(self, gemini_file_name: str) -> Optional[Dict[str, Any]]:
        """Find file metadata by Gemini file name."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchrow("""
                    SELECT id, original_filename, display_name,
                           mime_type, size_bytes, metadata, created_at, gemini_file_name
                    FROM file_uploads
                    WHERE gemini_file_name = $1
                    ORDER BY created_at DESC
                    LIMIT 1
                """, gemini_file_name)
        except Exception as e:
            logger.error(f"Error finding file by name: {e}")
            return None

    async def find_file_by_original_name(self, original_filename: str) -> Optional[Dict[str, Any]]:
        """Find file metadata by original filename."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchrow("""
                    SELECT id, original_filename, display_name,
                           mime_type, size_bytes, metadata, created_at, gemini_file_name
                    FROM file_uploads
                    WHERE original_filename = $1
                    ORDER BY created_at DESC
                    LIMIT 1
                """, original_filename)
        except Exception as e:
            logger.error(f"Error finding file by original name: {e}")
            return None

    async def find_file_by_partial_name(self, partial_name: str) -> Optional[Dict[str, Any]]:
        """Partial match lookup for files."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchrow("""
                    SELECT id, original_filename, display_name,
                           mime_type, size_bytes, metadata, created_at, gemini_file_name
                    FROM file_uploads
                    WHERE gemini_file_name LIKE $1
                    ORDER BY created_at DESC
                    LIMIT 1
                """, f"%{partial_name}%")
        except Exception as e:
            logger.error(f"Error finding file by partial name: {e}")
            return None

    async def find_file_by_basename(self, base_name: str) -> Optional[Dict[str, Any]]:
        """Fuzzy match by base name or display name."""
        try:
            async with get_db_connection() as conn:
                return await conn.fetchrow("""
                    SELECT id, original_filename, display_name,
                           mime_type, size_bytes, metadata, created_at, gemini_file_name
                    FROM file_uploads
                    WHERE original_filename LIKE $1 OR display_name LIKE $1
                    ORDER BY created_at DESC
                    LIMIT 1
                """, f"%{base_name}%")
        except Exception as e:
            logger.error(f"Error finding file by basename: {e}")
            return None
