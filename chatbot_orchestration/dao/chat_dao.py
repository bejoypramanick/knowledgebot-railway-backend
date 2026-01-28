import logging
from typing import Optional, Dict, Any, List
from shared import db

logger = logging.getLogger(__name__)

class ChatDAO:
    def __init__(self, database):
        self.db = database

    async def get_session_metadata(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve metadata for a chat session."""
        if not self.db:
            return None
            
        return await self.db.fetchrow("""
            SELECT file_search_store_id, cached_content_id, created_at, updated_at
            FROM chat_sessions 
            WHERE session_id = $1
            ORDER BY created_at DESC
            LIMIT 1
        """, session_id)

    async def update_session_metadata(self, session_id: str, file_search_store_id: str = None, cached_content_id: str = None):
        """Update or insert session metadata."""
        if not self.db:
            return
            
        await self.db.execute("""
            INSERT INTO chat_sessions (session_id, file_search_store_id, cached_content_id, created_at, updated_at)
            VALUES ($1, $2, $3, NOW(), NOW())
            ON CONFLICT (session_id) 
            DO UPDATE SET 
                file_search_store_id = COALESCE(EXCLUDED.file_search_store_id, chat_sessions.file_search_store_id),
                cached_content_id = COALESCE(EXCLUDED.cached_content_id, chat_sessions.cached_content_id),
                updated_at = NOW()
        """, session_id, file_search_store_id, cached_content_id)

    async def get_recent_files(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Retrieve recent file uploads metadata."""
        if not self.db:
            return []
            
        return await self.db.fetch("""
            SELECT gemini_file_name, original_filename, display_name, mime_type, size_bytes, created_at
            FROM file_uploads
            WHERE gemini_file_name IS NOT NULL
            ORDER BY created_at DESC
            LIMIT $1
        """, limit)

    async def find_file_by_name(self, gemini_file_name: str) -> Optional[Dict[str, Any]]:
        """Find file metadata by Gemini file name."""
        if not self.db:
            return None
            
        return await self.db.fetchrow("""
            SELECT id, original_filename, display_name,
                   mime_type, size_bytes, metadata, created_at, gemini_file_name
            FROM file_uploads
            WHERE gemini_file_name = $1
            ORDER BY created_at DESC
            LIMIT 1
        """, gemini_file_name)

    async def find_file_by_original_name(self, original_filename: str) -> Optional[Dict[str, Any]]:
        """Find file metadata by original filename."""
        if not self.db:
            return None
            
        return await self.db.fetchrow("""
            SELECT id, original_filename, display_name,
                   mime_type, size_bytes, metadata, created_at, gemini_file_name
            FROM file_uploads
            WHERE original_filename = $1
            ORDER BY created_at DESC
            LIMIT 1
        """, original_filename)

    async def find_file_by_partial_name(self, partial_name: str) -> Optional[Dict[str, Any]]:
        """Partial match lookup for files."""
        if not self.db:
            return None
            
        return await self.db.fetchrow("""
            SELECT id, original_filename, display_name,
                   mime_type, size_bytes, metadata, created_at, gemini_file_name
            FROM file_uploads
            WHERE gemini_file_name LIKE $1
            ORDER BY created_at DESC
            LIMIT 1
        """, f"%{partial_name}%")

    async def find_file_by_basename(self, base_name: str) -> Optional[Dict[str, Any]]:
        """Fuzzy match by base name or display name."""
        if not self.db:
            return None
            
        return await self.db.fetchrow("""
            SELECT id, original_filename, display_name,
                   mime_type, size_bytes, metadata, created_at, gemini_file_name
            FROM file_uploads
            WHERE original_filename LIKE $1 OR display_name LIKE $1
            ORDER BY created_at DESC
            LIMIT 1
        """, f"%{base_name}%")
