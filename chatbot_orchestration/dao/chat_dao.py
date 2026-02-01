"""
Chat Data Access Object for Chatbot Orchestration
Handles database operations for chat sessions and messages
"""
from typing import Dict, List, Any, Optional

from chatbot_orchestration.core.db import get_db_connection
from chatbot_orchestration.core.otel_logger import get_otel_logger

logger = get_otel_logger("chat_dao", "chatbot-orchestration")

class ChatDAO:
    """Unified Data Access Object for all chat operations"""
    
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_session_metadata(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session metadata from database"""
        query = """
            SELECT session_id, user_email, created_at, last_activity_at, message_count
            FROM chat_sessions
            WHERE session_id = $1
        """
        
        try:
            async with get_db_connection() as conn:
                record = await conn.fetchrow(query, session_id)
                logger.log_db_query(query, {"session_id": session_id}, record)
                
                if record:
                    return {
                        "session_id": record["session_id"],
                        "user_email": record["user_email"],
                        "created_at": record["created_at"],
                        "last_activity_at": record["last_activity_at"],
                        "message_count": record["message_count"]
                    }
                else:
                    return None
        except Exception as e:
            logger.log_db_query(query, {"session_id": session_id}, error=e)
            return None

    async def get_chat_history(self, session_id: str) -> List[Dict[str, Any]]:
        """Get chat history for a session"""
        query = """
            SELECT message_id, sender_type, sender_email, message_content, metadata, created_at
            FROM chat_messages
            WHERE session_id = $1
            ORDER BY created_at ASC
        """
        
        try:
            async with get_db_connection() as conn:
                records = await conn.fetch(query, session_id)
                logger.log_db_query(query, {"session_id": session_id}, records)
                return [dict(record) for record in records]
        except Exception as e:
            logger.log_db_query(query, {"session_id": session_id}, error=e)
            return []

    async def delete_session(self, session_id: str) -> bool:
        """Delete a chat session"""
        query = "DELETE FROM chat_sessions WHERE session_id = $1"
        
        try:
            async with get_db_connection() as conn:
                result = await conn.execute(query, session_id)
                logger.log_db_query(query, {"session_id": session_id}, result)
                return True
        except Exception as e:
            logger.log_db_query(query, {"session_id": session_id}, error=e)
            return False

    async def get_all_sessions(self) -> List[Dict[str, Any]]:
        """Get all chat sessions"""
        query = """
            SELECT session_id, user_email, metadata, created_at, last_activity_at
            FROM chat_sessions
            ORDER BY last_activity_at DESC
        """
        
        try:
            async with get_db_connection() as conn:
                records = await conn.fetch(query)
                logger.log_db_query(query, None, records)
                return [dict(record) for record in records]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []
