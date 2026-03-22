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

    async def create_session(self, session_id: str, user_role_id: str = None) -> Optional[Dict[str, Any]]:
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
                "id": session.get("session_uuid"),
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

    async def get_user_email_from_role_id(self, user_role_id: str) -> Optional[str]:
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

    async def create_session_pg(self) -> Optional[str]:
        """
        Create a new chat session in PG18 using database-generated UUIDv7.
        Returns the UUIDv7 id as the session identifier.
        PG18: id IS the session identifier — no separate session_id/db_id.
        """
        try:
            async with get_db_session() as db_session:
                result = await db_session.execute(
                    text("""
                        INSERT INTO chat_sessions (id, is_active, archive_status, started_at, last_activity_at, message_count)
                        VALUES (uuidv7(), true, 'active', NOW(), NOW(), 0)
                        RETURNING id
                    """)
                )
                session_id = str(result.scalar())
                await db_session.commit()

                logger.info(f"PG18 session created with UUIDv7: {session_id}")
                return session_id

        except Exception as e:
            logger.error(f"Error creating PG18 session: {e}")
            return None

    async def ensure_session_exists(self, session_id: str, metadata: dict = None) -> Optional[str]:
        """
        Ensure session exists in PG. Creates row if needed (idempotent).
        PG18: id IS the UUIDv7 PK — no separate session_id column.
        Stores customer_email in metadata JSONB on first creation.
        """
        try:
            import json as _json
            metadata_json = _json.dumps(metadata) if metadata else '{}'
            async with get_db_session() as db_session:
                result = await db_session.execute(
                    text("""
                        INSERT INTO chat_sessions (id, is_active, archive_status, started_at, last_activity_at, message_count, metadata)
                        VALUES (CAST(:id AS UUID), true, 'active', NOW(), NOW(), 0, CAST(:metadata AS JSONB))
                        ON CONFLICT (id) DO UPDATE SET
                            last_activity_at = NOW(),
                            metadata = CASE
                                WHEN chat_sessions.metadata IS NULL OR chat_sessions.metadata = '{}'::jsonb
                                THEN CAST(:metadata AS JSONB)
                                ELSE chat_sessions.metadata
                            END
                        RETURNING id
                    """),
                    {"id": session_id, "metadata": metadata_json}
                )
                db_id = str(result.scalar())
                await db_session.commit()

                logger.info(f"PG18 session ensured: {session_id}")
                return db_id

        except Exception as e:
            logger.error(f"Error ensuring PG18 session {session_id}: {e}")
            return None

    async def delete_session(self, session_id: str) -> bool:
        """Delete a chat session from both Redis and PG."""
        await self._store.delete_session(session_id)

        query = "DELETE FROM chat_sessions WHERE id = CAST(:id AS UUID)"
        try:
            async with get_db_session() as session:
                await session.execute(text(query), {"id": session_id})
                await session.commit()
                logger.info(f"Session deleted from Redis + PG: {session_id}")
                return True
        except Exception as e:
            logger.error(f"Error deleting session from PG: {e}")
            return False

    async def get_all_sessions(self) -> List[Dict[str, Any]]:
        """Get all chat sessions (admin cold path — PG only)."""
        query = """
            SELECT id, user_role_id, metadata, created_at, last_activity_at
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
