"""
Chat Data Access Object for Chatbot Orchestration
Handles database operations for chat sessions and messages
"""
from typing import Dict, Any, Optional

from chatbot_orchestration.core.db import get_db_connection
from chatbot_orchestration.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class LocalChatDAO:
    """Data access object for local chat operations"""
    
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_session_metadata(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session metadata from database"""
        try:
            async with get_db_connection() as conn:
                record = await conn.fetchrow("""
                    SELECT session_id, metadata, created_at, last_activity_at
                    FROM chat_sessions 
                    WHERE session_id = $1
                """, session_id)
                
                if record:
                    return {
                        'session_id': record['session_id'],
                        'metadata': record['metadata'],
                        'created_at': record['created_at'],
                        'last_activity_at': record['last_activity_at'],
                        'is_new_session': False
                    }
                else:
                    return None
        except Exception as e:
            logger.error(f"Error getting session metadata for {session_id}: {e}")
            return None

class SharedChatDAO:
    """Data access object for shared chat operations"""
    
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection
