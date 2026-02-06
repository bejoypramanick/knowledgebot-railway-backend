"""
Chat Data Access Object for Chatbot Orchestration
Handles database operations for chat sessions and messages
"""
from typing import Dict, List, Any, Optional

from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("chat_dao", "chatbot-orchestration")

class ChatDAO:
    """Unified Data Access Object for all chat operations"""
    
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def create_session(self, session_id: str, user_role_id: int = None) -> Optional[Dict[str, Any]]:
        """Create a new chat session record"""
        query = """
            INSERT INTO chat_sessions (session_id, user_role_id, started_at, last_activity_at, is_active, message_count)
            VALUES ($1, $2, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, true, 0)
            RETURNING id, session_id, user_role_id, started_at, last_activity_at, is_active, message_count
        """
        params = {"session_id": session_id, "user_role_id": user_role_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                record = await conn.fetchrow(query, session_id, user_role_id)
                logger.log_db_query(query, params, record)
                
                if record:
                    return {
                        "id": record["id"],
                        "session_id": record["session_id"],
                        "user_role_id": record["user_role_id"],
                        "started_at": record["started_at"].isoformat() if record["started_at"] else None,
                        "last_activity_at": record["last_activity_at"].isoformat() if record["last_activity_at"] else None,
                        "is_active": record["is_active"],
                        "message_count": record["message_count"]
                    }
                else:
                    return None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def get_session_metadata(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session metadata from database"""
        query = """
            SELECT session_id, user_role_id, cached_content_id, created_at, last_activity_at, message_count
            FROM chat_sessions
            WHERE session_id = $1
        """
        params = {"session_id": session_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                record = await conn.fetchrow(query, session_id)
                logger.log_db_query(query, params, record)
                
                if record:
                    user_email = await self.get_user_email_from_role_id(record["user_role_id"])
                    
                    return {
                        "session_id": record["session_id"],
                        "user_role_id": record["user_role_id"],
                        "user_email": user_email,
                        "cached_content_id": record["cached_content_id"],
                        "created_at": record["created_at"],
                        "last_activity_at": record["last_activity_at"],
                        "message_count": record["message_count"]
                    }
                return None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def get_user_email_from_role_id(self, user_role_id: int) -> Optional[str]:
        """Get user email from user_role_id"""
        if user_role_id is None:
            return None
        query = """
            SELECT u.email
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            WHERE urm.user_role_id = $1 AND urm.is_active = true
        """
        params = {"user_role_id": user_role_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                record = await conn.fetchrow(query, user_role_id)
                logger.log_db_query(query, params, record)
                return record["email"] if record else None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def get_chat_history(self, session_id: str) -> Dict[str, Any]:
        """Get chat history for a session"""
        session_query = """
            SELECT id, session_id, user_role_id, cached_content_id, created_at, last_activity_at, message_count
            FROM chat_sessions
            WHERE session_id = $1
        """
        try:
            async with get_db_connection() as conn:
                logger.log_db_operation(session_query, session_id)
                session_record = await conn.fetchrow(session_query, session_id)
                logger.log_db_query(session_query, session_id, session_record)
                
                if not session_record:
                    insert_query = """INSERT INTO chat_sessions (session_id, user_role_id, started_at, last_activity_at, is_active, message_count)
                                   VALUES ($1, NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, true, 0)
                                   RETURNING id, session_id, user_role_id, cached_content_id, created_at, last_activity_at, message_count"""
                    logger.log_db_operation(insert_query, session_id)
                    session_record = await conn.fetchrow(insert_query, session_id)
                    logger.log_db_query(insert_query, session_id, session_record)
                    
                    if not session_record:
                        return {"messages": []}
                
                integer_session_id = session_record["id"]
                
                query = """
                    SELECT id, role, content, created_at, used_rag, sources, confidence_score
                    FROM chat_messages
                    WHERE session_id = $1
                    ORDER BY created_at ASC
                """
                logger.log_db_operation(query, integer_session_id)
                records = await conn.fetch(query, integer_session_id)
                logger.log_db_query(query, integer_session_id, records)
                
                messages = []
                for record in records:
                    messages.append({
                        "id": str(record["id"]),
                        "sender": "user" if record["role"] == "user" else "agent",
                        "message": record["content"],
                        "role": record["role"],
                        "created_at": record["created_at"].isoformat() if record["created_at"] else None,
                        "used_rag": record["used_rag"],
                        "sources": record["sources"] or [],
                        "confidence_score": float(record["confidence_score"]) if record["confidence_score"] else None
                    })
                
                return {"messages": messages}
        except Exception as e:
            logger.error(f"Error getting chat history for {session_id}: {e}")
            return {"messages": []}

    async def delete_session(self, session_id: str) -> bool:
        """Delete a chat session"""
        query = "DELETE FROM chat_sessions WHERE session_id = $1"
        params = {"session_id": session_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, session_id)
                logger.log_db_query(query, params, result)
                return True
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False

    async def get_all_sessions(self) -> List[Dict[str, Any]]:
        """Get all chat sessions"""
        query = """
            SELECT session_id, user_email, metadata, created_at, last_activity_at
            FROM chat_sessions
            ORDER BY last_activity_at DESC
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                records = await conn.fetch(query)
                logger.log_db_query(query, None, records)
                return [dict(record) for record in records]
        except Exception as e:
            logger.log_db_query(query, None, error=e)
            return []
