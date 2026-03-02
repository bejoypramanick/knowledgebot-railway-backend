"""
Session Persistence DAO for Chatbot Orchestration
Handles database operations for chat sessions and messages
"""
from typing import Optional, Dict, Any
from datetime import datetime

from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("session_persistence_dao", "chatbot-orchestration")


class SessionPersistenceDAO:
    """DAO for persisting chat sessions and messages to database"""

    async def get_or_create_session(self, session_id: str) -> int:
        """
        Get existing session database ID or create new session.

        Args:
            session_id: The unique session identifier

        Returns:
            The database ID of the session
        """
        query_get = "SELECT id FROM chat_sessions WHERE session_id = :session_id"
        query_create = """
            INSERT INTO chat_sessions (session_id, is_active, archive_status, started_at, last_activity_at)
            VALUES (:session_id, true, 'active', NOW(), NOW())
            RETURNING id
        """

        try:
            async with get_db_session() as session:
                # Check if session exists
                result = (await session.execute(text(query_get), {"session_id": session_id})).scalar()
                if result:
                    logger.info(f"📋 Using existing session: {session_id} (DB ID: {result})")
                    return result

                # Create new session
                session_db_id = (await session.execute(text(query_create), {"session_id": session_id})).scalar()
                await session.commit()
                logger.info(f"✨ Created new session: {session_id} (DB ID: {session_db_id})")
                return session_db_id

        except Exception as e:
            logger.error(f"❌ Error in get_or_create_session: {e}", exc_info=True)
            raise

    async def save_user_message(self, session_db_id: int, content: str) -> int:
        """
        Save a user message to the database.

        Args:
            session_db_id: The database ID of the session
            content: The message content

        Returns:
            The database ID of the created message
        """
        query = """
            INSERT INTO chat_messages (session_id, role, content, created_at, updated_at)
            VALUES (:session_db_id, 'user', :content, NOW(), NOW())
            RETURNING id
        """

        try:
            async with get_db_session() as session:
                message_id = (await session.execute(text(query), {"session_db_id": session_db_id, "content": content})).scalar()
                logger.debug(f"💾 Saved user message: {message_id} to session {session_db_id}")

                # Update session last_activity_at and message_count
                await self._update_session_activity(session, session_db_id)

                return message_id

        except Exception as e:
            logger.error(f"❌ Error saving user message: {e}", exc_info=True)
            raise

    async def save_bot_message(self, session_db_id: int, content: str, role: str = 'bot') -> int:
        """
        Save a bot/AI response message to the database.

        Args:
            session_db_id: The database ID of the session
            content: The message content
            role: The role (default 'bot', can be 'system', 'agent', etc.)

        Returns:
            The database ID of the created message
        """
        query = """
            INSERT INTO chat_messages (session_id, role, content, created_at, updated_at)
            VALUES (:session_db_id, :role, :content, NOW(), NOW())
            RETURNING id
        """

        try:
            async with get_db_session() as session:
                message_id = (await session.execute(text(query), {"session_db_id": session_db_id, "role": role, "content": content})).scalar()
                logger.debug(f"💾 Saved {role} message: {message_id} to session {session_db_id}")

                # Update session last_activity_at and message_count
                await self._update_session_activity(session, session_db_id)

                return message_id

        except Exception as e:
            logger.error(f"❌ Error saving bot message: {e}", exc_info=True)
            raise

    async def update_session_activity(self, session_db_id: int) -> bool:
        """
        Update the last_activity_at timestamp for a session.

        Args:
            session_db_id: The database ID of the session

        Returns:
            True if successful
        """
        try:
            async with get_db_session() as session:
                await self._update_session_activity(session, session_db_id)
                return True
        except Exception as e:
            logger.error(f"❌ Error updating session activity: {e}", exc_info=True)
            return False

    async def _update_session_activity(self, session, session_db_id: int) -> None:
        """
        Internal method to update session activity.

        Args:
            session: The database session
            session_db_id: The database ID of the session
        """
        query = """
            UPDATE chat_sessions
            SET last_activity_at = NOW(),
                message_count = message_count + 1,
                updated_at = NOW()
            WHERE id = :session_db_id
        """

        try:
            await session.execute(text(query), {"session_db_id": session_db_id})
            await session.commit()
        except Exception as e:
            logger.error(f"❌ Error updating session activity in DB: {e}", exc_info=True)
            # Don't re-raise to avoid blocking message saving

    async def get_session_message_count(self, session_db_id: int) -> int:
        """
        Get the message count for a session.

        Args:
            session_db_id: The database ID of the session

        Returns:
            The number of messages in the session
        """
        query = "SELECT COUNT(*) FROM chat_messages WHERE session_id = :session_db_id"

        try:
            async with get_db_session() as session:
                count = (await session.execute(text(query), {"session_db_id": session_db_id})).scalar()
                return count or 0
        except Exception as e:
            logger.error(f"❌ Error getting message count: {e}", exc_info=True)
            return 0

    async def close_session(self, session_db_id: int) -> bool:
        """
        Mark a session as closed.

        Args:
            session_db_id: The database ID of the session

        Returns:
            True if successful
        """
        query = """
            UPDATE chat_sessions
            SET is_active = false,
                archive_status = 'closed',
                ended_at = NOW(),
                updated_at = NOW()
            WHERE id = :session_db_id
        """

        try:
            async with get_db_session() as session:
                await session.execute(text(query), {"session_db_id": session_db_id})
                await session.commit()
                logger.info(f"🔒 Closed session: {session_db_id}")
                return True
        except Exception as e:
            logger.error(f"❌ Error closing session: {e}", exc_info=True)
            return False
