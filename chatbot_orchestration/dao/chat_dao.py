"""
Chat Data Access Object for Chatbot Orchestration
Redis-primary storage (DB 6). PG is written asynchronously via write-through.
Hot-path reads/writes go to Redis only — zero PG connections during SSE streaming.
"""
from typing import Dict, List, Any, Optional

from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
from shared.otel_logger import get_otel_logger
from shared.redis_chat_store import get_chat_store

logger = get_otel_logger("chat_dao", "chatbot-orchestration")

class ChatDAO:
    """Unified Data Access Object for all chat operations (Redis-primary)"""

    def __init__(self):
        self._store = get_chat_store()

    async def create_session(self, session_id: str, user_role_id: int = None) -> Optional[Dict[str, Any]]:
        """
        Create a new chat session in Redis.
        PG row is created lazily by write-through or on first message (for numeric ID).
        """
        session = await self._store.get_or_create_session(
            session_uuid=session_id,
            user_role_id=user_role_id
        )
        if session:
            logger.info(f"Session created in Redis: {session_id}")
            return {
                "id": session.get("db_id"),
                "session_id": session.get("session_uuid"),
                "user_role_id": session.get("user_role_id"),
                "started_at": session.get("started_at"),
                "last_activity_at": session.get("last_activity_at"),
                "is_active": session.get("is_active"),
                "message_count": session.get("message_count")
            }
        return None

    async def get_session_metadata(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session metadata from Redis."""
        session = await self._store.get_session(session_id)
        if session:
            user_email = await self.get_user_email_from_role_id(session.get("user_role_id"))
            return {
                "session_id": session.get("session_uuid"),
                "user_role_id": session.get("user_role_id"),
                "user_email": user_email,
                "created_at": session.get("started_at"),
                "last_activity_at": session.get("last_activity_at"),
                "message_count": session.get("message_count")
            }
        return None

    async def get_user_email_from_role_id(self, user_role_id: int) -> Optional[str]:
        """Get user email from user_role_id (PG lookup — cold path, rarely called)."""
        if user_role_id is None:
            return None
        query = """
            SELECT u.email
            FROM user_role_mapping urm
            JOIN users u ON urm.user_id = u.id
            WHERE urm.user_role_id = :user_role_id AND urm.is_active = true
        """
        params = {"user_role_id": user_role_id}
        try:
            async with get_db_session() as session:
                record = (await session.execute(text(query), params)).fetchone()
                return record.email if record else None
        except Exception as e:
            logger.error(f"Error getting email for role {user_role_id}: {e}")
            return None

    async def get_chat_history(self, session_id: str) -> Dict[str, Any]:
        """
        Get chat history from Redis.
        If session doesn't exist in Redis, creates it (lazy creation).
        """
        # Ensure session exists in Redis
        await self._store.get_or_create_session(session_uuid=session_id)

        # Get messages from Redis
        redis_messages = await self._store.get_messages(session_id)

        messages = []
        for i, msg in enumerate(redis_messages):
            messages.append({
                "id": str(i),
                "sender": "user" if msg.get("role") == "user" else "agent",
                "message": msg.get("content", ""),
                "role": msg.get("role", ""),
                "content": msg.get("content", ""),
                "created_at": msg.get("created_at"),
                "used_rag": msg.get("metadata", {}).get("used_rag") if isinstance(msg.get("metadata"), dict) else None,
                "sources": msg.get("metadata", {}).get("sources", []) if isinstance(msg.get("metadata"), dict) else [],
                "confidence_score": msg.get("metadata", {}).get("confidence_score") if isinstance(msg.get("metadata"), dict) else None
            })

        return {"messages": messages}

    async def ensure_numeric_id(self, session_id: str) -> Optional[int]:
        """
        Ensure session has a PG numeric ID. Creates PG row if needed.
        This is the ONLY PG call in the hot path — happens once per new session.
        """
        # Check if we already have a db_id cached in Redis
        session = await self._store.get_session(session_id)
        if session and session.get("db_id"):
            return session["db_id"]

        # Need to create PG row to get serial ID
        try:
            async with get_db_session() as db_session:
                result = await db_session.execute(
                    text("""
                        INSERT INTO chat_sessions (session_id, is_active, archive_status, started_at, last_activity_at, message_count)
                        VALUES (:session_id, true, 'active', NOW(), NOW(), 0)
                        ON CONFLICT (session_id) DO UPDATE SET last_activity_at = NOW()
                        RETURNING id
                    """),
                    {"session_id": session_id}
                )
                db_id = result.scalar()
                await db_session.commit()

                # Cache the db_id in Redis
                await self._store.set_session_db_id(session_id, db_id)
                logger.info(f"PG numeric ID created for {session_id}: {db_id}")
                return db_id

        except Exception as e:
            logger.error(f"Error creating PG numeric ID for {session_id}: {e}")
            return None

    async def delete_session(self, session_id: str) -> bool:
        """Delete a chat session from both Redis and PG."""
        await self._store.delete_session(session_id)

        query = "DELETE FROM chat_sessions WHERE session_id = :session_id"
        try:
            async with get_db_session() as session:
                await session.execute(text(query), {"session_id": session_id})
                await session.commit()
                logger.info(f"Session deleted from Redis + PG: {session_id}")
                return True
        except Exception as e:
            logger.error(f"Error deleting session from PG: {e}")
            return False

    async def get_all_sessions(self) -> List[Dict[str, Any]]:
        """Get all chat sessions (admin cold path — PG only)."""
        query = """
            SELECT session_id, user_email, metadata, created_at, last_activity_at
            FROM chat_sessions
            ORDER BY last_activity_at DESC
        """
        try:
            async with get_db_session() as session:
                records = (await session.execute(text(query))).fetchall()
                return [dict(record._mapping) for record in records]
        except Exception as e:
            logger.error(f"Error getting all sessions: {e}")
            return []
