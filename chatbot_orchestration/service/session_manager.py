"""
Session State Management for Chatbot Orchestration
Handles session state, caching, and metadata management.
Uses Redis DB 6 for hot-path message storage and DB 4 for agent cache.
PG is written asynchronously via write-through — no direct PG reads/writes here.
"""

import time
import asyncio
from datetime import datetime, timedelta
from typing import Dict, Any, Optional

from shared.otel_logger import get_otel_logger

from ..core.ai import get_genai_client, MODEL_NAME
from ..dao.chat_dao import ChatDAO

logger = get_otel_logger("session_manager", "chatbot-orchestration")

class SessionStateManager:
    """Manages session state, caching, and metadata for chat sessions."""

    def __init__(self):
        self.genai_client = None
        self.chat_dao = ChatDAO()
        self.session_states: Dict[str, Dict[str, Any]] = {}

    async def initialize(self):
        """Initialize the session manager with required clients."""
        if not self.genai_client:
            self.genai_client = get_genai_client()

    async def get_session_metadata(self, session_id: str) -> Dict[str, Any]:
        """Retrieve session metadata from Redis."""
        try:
            metadata = await self.chat_dao.get_session_metadata(session_id)
            if metadata:
                return metadata
            else:
                logger.warning(f"No metadata found for session: {session_id}")
                return {}
        except Exception as e:
            logger.error(f"Error retrieving session metadata: {e}")
            return {}

    def get_session_state(self, session_id: str) -> Dict[str, Any]:
        """Get or create session state."""
        if session_id not in self.session_states:
            self.session_states[session_id] = {
                'created_at': time.time(),
                'last_activity': time.time(),
                'message_count': 0,
                'is_streaming': False
            }
        return self.session_states[session_id]

    async def get_chat_history(self, session_id: str):
        """Get chat history from Redis."""
        result = await self.chat_dao.get_chat_history(session_id)
        return result.get("messages", []) if result else []

    async def save_message(self, session_id: str, role: str, content: str, metadata: Dict[str, Any] = None):
        """
        Save message to Redis (DB 6) with lazy session creation.
        PG write-through handles durable archival in background.
        """
        try:
            from shared.redis_chat_store import get_chat_store

            store = get_chat_store()

            # Ensure session exists in Redis (lazy creation)
            # Pass customer_email from metadata so chat log shows the user identity
            session_metadata = {}
            if metadata and metadata.get("user_email"):
                session_metadata["customer_email"] = metadata["user_email"]
            session_data = await store.get_or_create_session(
                session_uuid=session_id,
                metadata=session_metadata if session_metadata else None
            )

            # PG18: session_id IS the UUIDv7 PK — ensure PG row exists (with metadata)
            await self.chat_dao.ensure_session_exists(session_id, metadata=session_metadata if session_metadata else None)

            # Save message to Redis (atomic pipeline: RPUSH + HINCRBY + HSET + SADD)
            result = await store.save_message(session_id, role, content, metadata)

            if not result:
                logger.error(f"Redis save_message failed for session {session_id}")
                return None

            logger.debug(f"Saved {role} message to Redis: {session_id}")

            message_data = {
                "id": result.get("index", 0),
                "session_id": session_id,
                "role": role,
                "content": content,
                "created_at": result.get("created_at")
            }

            # Broadcast messages to agents in real-time via Redis Pub/Sub
            if role in ["user", "assistant"]:
                await self._broadcast_message(session_id, role, content, message_data)

            return message_data

        except Exception as e:
            logger.error(f"Error saving message to Redis: {e}")
            return None

    async def _broadcast_message(self, session_id: str, role: str, content: str, message_data: dict):
        """Broadcast message to agents via Redis Pub/Sub. Uses DB 4 for agent cache."""
        try:
            from shared.redis_pubsub_manager import broadcast_event_for_session
            from shared.redis_agent_cache import get_assigned_agent, set_assigned_agent

            # Check DB 4 agent cache first
            assigned_agent = await get_assigned_agent(session_id)

            if not assigned_agent:
                # Cache miss — query database (cold path, once per session)
                try:
                    from shared.sqlalchemy_db import get_db_session
                    from sqlalchemy import text

                    async with get_db_session() as db_session:
                        # PG18: id IS the UUIDv7 PK — no separate session_id column
                        session_result = await db_session.execute(
                            text("SELECT id FROM chat_sessions WHERE id = CAST(:session_id AS UUID)"),
                            {"session_id": session_id}
                        )
                        session_row = session_result.mappings().first()
                        if session_row:
                            uuid_session_id = str(session_row["id"])
                            assignment_query = """
                                SELECT u.email as agent_email
                                FROM session_assignments sa
                                LEFT JOIN user_role_mapping urm ON sa.user_role_id = urm.user_role_id
                                LEFT JOIN users u ON urm.user_id = u.id
                                WHERE sa.session_id = CAST(:session_id AS UUID) AND sa.status = 'active'
                            """
                            assignment_result = await db_session.execute(
                                text(assignment_query),
                                {"session_id": uuid_session_id}
                            )
                            assignment = assignment_result.mappings().first()
                            assigned_agent = assignment["agent_email"] if assignment else None

                            if assigned_agent:
                                await set_assigned_agent(session_id, assigned_agent)
                                logger.info(f"Cached agent assignment (DB 4): {session_id} -> {assigned_agent}")
                except Exception as db_error:
                    logger.warning(f"DB agent lookup failed: {db_error}")

            # Broadcast to session + agent channels
            event_data = {
                "type": "customer_message" if role == "user" else "bot_message",
                "message_id": str(message_data.get("id", 0)),
                "session_id": session_id,
                "text": content,
                "sender": "customer" if role == "user" else "bot",
                "timestamp": message_data.get("created_at")
            }

            await broadcast_event_for_session(session_id, event_data, assigned_agent)
            logger.info(f"Broadcasted {role} message to session {session_id}")
        except Exception as broadcast_error:
            logger.warning(f"Failed to broadcast {role} message: {broadcast_error}")

    def update_session_activity(self, session_id: str):
        """Update session activity timestamp."""
        state = self.get_session_state(session_id)
        state['last_activity'] = time.time()
        state['message_count'] += 1

    def set_streaming_state(self, session_id: str, is_streaming: bool):
        """Set streaming state for a session."""
        state = self.get_session_state(session_id)
        state['is_streaming'] = is_streaming

    def cleanup_expired_sessions(self, max_age_hours: int = 24):
        """Clean up expired sessions."""
        current_time = time.time()
        expired_sessions = []

        for session_id, state in self.session_states.items():
            age_hours = (current_time - state['last_activity']) / 3600
            if age_hours > max_age_hours:
                expired_sessions.append(session_id)

        for session_id in expired_sessions:
            del self.session_states[session_id]
            logger.info(f"Cleaned up expired session: {session_id}")

    def get_turn_count(self, session_id: str) -> int:
        """Get the turn count for a session."""
        state = self.get_session_state(session_id)
        return state.get('message_count', 0)

    def is_new_session(self, session_id: str) -> bool:
        """Check if this is a new session."""
        state = self.get_session_state(session_id)
        return state.get('message_count', 0) == 0

    def get_message_history(self, session_id: str) -> list:
        """Get message history for a session (synchronous version)."""
        return []

    def update_session_state(self, session_id: str, result: Any) -> Dict[str, Any]:
        """Update session state with result from agent."""
        state = self.get_session_state(session_id)
        state['last_result'] = result
        state['last_activity'] = time.time()
        return state

# Global session manager instance
session_state_manager = SessionStateManager()
