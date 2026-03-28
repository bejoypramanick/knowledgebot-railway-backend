"""
Session Persistence DAO for Chatbot Orchestration
Redirects to Redis chat store (DB 6). PG is written asynchronously via write-through.

PG18: session_id IS the UUIDv7 database PK — no separate db_id/numeric_id.
"""
from typing import Optional, Dict, Any

from shared.otel_logger import get_otel_logger
from shared.redis_chat_store import get_chat_store

logger = get_otel_logger("session_persistence_dao", "chatbot-orchestration")


class SessionPersistenceDAO:
    """DAO for persisting chat sessions and messages — Redis-primary"""

    def __init__(self):
        self._store = get_chat_store()

    async def create_session(self) -> str:
        """
        Create a new session with PG18 database-generated UUIDv7.
        Returns the UUIDv7 string which IS the session identifier and database PK.
        """
        from chatbot_orchestration.dao.chat_dao import ChatDAO
        chat_dao = ChatDAO()
        session_id = await chat_dao.create_session_pg()
        if not session_id:
            raise RuntimeError("Failed to create PG18 session")

        # Create Redis session with the PG-generated UUID
        await self._store.get_or_create_session(session_uuid=session_id)
        return session_id

    async def ensure_session(self, session_id: str) -> str:
        """
        Ensure session exists in both Redis and PG (idempotent).
        PG18: session_id IS the UUIDv7 PK — no resolution needed.
        """
        # Ensure session exists in Redis
        await self._store.get_or_create_session(session_uuid=session_id)

        # Ensure session exists in PG
        from chatbot_orchestration.dao.chat_dao import ChatDAO
        chat_dao = ChatDAO()
        await chat_dao.ensure_session_exists(session_id)

        return session_id

    async def save_user_message(self, session_id: str, content: str) -> int:
        """Save a user message — delegated to session_manager via Redis."""
        logger.debug(f"save_user_message called for session {session_id} — delegating to Redis via session_manager")
        return 0

    async def save_bot_message(self, session_id: str, content: str, role: str = 'bot') -> int:
        """Save a bot/AI response message — delegated to session_manager via Redis."""
        logger.debug(f"save_bot_message called for session {session_id} — delegating to Redis via session_manager")
        return 0

    async def update_session_activity(self, session_id: str) -> bool:
        """Update session activity — no-op, handled atomically by Redis save_message pipeline."""
        return True

    async def get_session_message_count(self, session_id: str) -> int:
        """Get message count — tracked in Redis hash."""
        return 0

    async def close_session(self, session_id: str) -> bool:
        """
        Mark a session as closed.
        PG18: session_id IS the UUIDv7 PK — no lookup needed.
        """
        try:
            from shared.sqlalchemy_db import get_db_session
            from sqlalchemy import text

            # Close in Redis
            await self._store.close_session(session_id)

            # Trigger immediate PG flush
            from shared.redis_chat_writethrough import ChatWriteThroughService
            writethrough = ChatWriteThroughService.get_instance()
            await writethrough.flush_now(session_id)

            # Also update PG directly for immediate consistency
            async with get_db_session() as db:
                await db.execute(
                    text("""
                        UPDATE chat_sessions
                        SET is_active = false, archive_status = 'closed',
                            ended_at = NOW(), updated_at = NOW()
                        WHERE id = CAST(:id AS UUID)
                    """),
                    {"id": session_id}
                )
                await db.commit()

            from chatbot_orchestration.service.agent_manager import agent_manager
            await agent_manager.clear_agent_cache(session_id)

            logger.info(f"Session closed: {session_id}")
            return True

        except Exception as e:
            logger.error(f"Error closing session {session_id}: {e}", exc_info=True)
            return False
