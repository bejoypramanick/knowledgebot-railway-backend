"""
Chat Data Access Object for Chatbot Orchestration
Handles database operations for chat sessions and messages
"""
from typing import Dict, List, Any, Optional

from chatbot_orchestration.core.db import get_db_connection
from chatbot_orchestration.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class ChatDAO:
    """Unified Data Access Object for all chat operations"""
    
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

    async def get_chat_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Get chat history for a session"""
        try:
            async with get_db_connection() as conn:
                records = await conn.fetch("""
                    SELECT message_id, sender_type, sender_email, message_content, metadata, created_at
                    FROM chat_messages
                    WHERE session_id = $1
                    ORDER BY created_at ASC
                """, session_id)
                return [dict(record) for record in records]
        except Exception as e:
            logger.error(f"Error getting chat history for session {session_id}: {e}")
            return []

    async def delete_session(self, session_id: str) -> bool:
        """Delete a chat session"""
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(
                    "DELETE FROM chat_sessions WHERE session_id = $1",
                    session_id
                )
                logger.info(f"Deleted chat session: {session_id}")
                return True
        except Exception as e:
            logger.error(f"Error deleting session {session_id}: {e}")
            return False

    async def get_all_sessions(self) -> List[Dict[str, Any]]:
        """Get all chat sessions"""
        try:
            async with get_db_connection() as conn:
                records = await conn.fetch("""
                    SELECT session_id, user_email, metadata, created_at, last_activity_at
                    FROM chat_sessions
                    ORDER BY last_activity_at DESC
                """)
                return [dict(record) for record in records]
        except Exception as e:
            logger.error(f"Error getting all sessions: {e}")
            return []
