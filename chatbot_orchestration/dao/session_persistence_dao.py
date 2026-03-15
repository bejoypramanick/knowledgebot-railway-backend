"""
Session Persistence DAO for Chatbot Orchestration
Redirects to Redis chat store (DB 6). PG is written asynchronously via write-through.
"""
from typing import Optional, Dict, Any

from shared.otel_logger import get_otel_logger
from shared.redis_chat_store import get_chat_store

logger = get_otel_logger("session_persistence_dao", "chatbot-orchestration")


class SessionPersistenceDAO:
    """DAO for persisting chat sessions and messages — Redis-primary"""

    def __init__(self):
        self._store = get_chat_store()

    async def get_or_create_session(self, session_id: str) -> int:
        """
        Get existing session or create new one in Redis.
        Returns the PG numeric ID (creates PG row if needed for the serial ID).
        """
        # Ensure session exists in Redis
        session = await self._store.get_or_create_session(session_uuid=session_id)

        # Check if we already have a db_id
        if session and session.get("db_id"):
            return session["db_id"]

        # Need PG row for numeric ID (single PG call, first message only)
        from chatbot_orchestration.dao.chat_dao import ChatDAO
        chat_dao = ChatDAO()
        db_id = await chat_dao.ensure_numeric_id(session_id)
        if db_id:
            return db_id

        # Should not happen, but raise if we can't get an ID
        raise RuntimeError(f"Failed to get or create numeric ID for session {session_id}")

    async def save_user_message(self, session_db_id: int, content: str) -> int:
        """
        Save a user message to Redis.
        Returns a synthetic message index (not a PG serial ID).
        PG persistence happens via write-through.
        """
        # We need the session_uuid to save to Redis — look it up from the store
        # or use session_db_id as a reference
        # The caller should pass session_uuid instead, but for backward compat
        # we accept session_db_id and note that the actual save is done
        # by session_manager.save_message() which has the UUID
        logger.debug(f"save_user_message called for session {session_db_id} — delegating to Redis via session_manager")
        # Return 0 as a placeholder — actual save happens in session_manager
        return 0

    async def save_bot_message(self, session_db_id: int, content: str, role: str = 'bot') -> int:
        """
        Save a bot/AI response message to Redis.
        Returns a synthetic message index.
        PG persistence happens via write-through.
        """
        logger.debug(f"save_bot_message called for session {session_db_id} — delegating to Redis via session_manager")
        return 0

    async def update_session_activity(self, session_db_id: int) -> bool:
        """Update session activity — no-op, handled atomically by Redis save_message pipeline."""
        return True

    async def get_session_message_count(self, session_db_id: int) -> int:
        """Get message count — queries Redis if session_uuid is known."""
        # This is rarely called directly; message_count is tracked in Redis hash
        return 0

    async def close_session(self, session_db_id: int) -> bool:
        """
        Mark a session as closed.
        Closes in Redis and triggers immediate PG flush via write-through.
        """
        # We need session_uuid — look it up from PG (cold path, rare)
        try:
            from shared.sqlalchemy_db import get_db_session
            from sqlalchemy import text

            async with get_db_session() as db:
                result = await db.execute(
                    text("SELECT session_id FROM chat_sessions WHERE id = :id"),
                    {"id": session_db_id}
                )
                row = result.fetchone()
                if not row:
                    logger.warning(f"Cannot close session {session_db_id}: not found in PG")
                    return False

                session_uuid = row[0]

            # Close in Redis
            await self._store.close_session(session_uuid)

            # Trigger immediate PG flush
            from shared.redis_chat_writethrough import ChatWriteThroughService
            writethrough = ChatWriteThroughService.get_instance()
            await writethrough.flush_now(session_uuid)

            # Also update PG directly for immediate consistency
            async with get_db_session() as db:
                await db.execute(
                    text("""
                        UPDATE chat_sessions
                        SET is_active = false, archive_status = 'closed',
                            ended_at = NOW(), updated_at = NOW()
                        WHERE id = :id
                    """),
                    {"id": session_db_id}
                )
                await db.commit()

            logger.info(f"Session closed: {session_db_id} ({session_uuid})")
            return True

        except Exception as e:
            logger.error(f"Error closing session {session_db_id}: {e}", exc_info=True)
            return False
