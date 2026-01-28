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

    
    
