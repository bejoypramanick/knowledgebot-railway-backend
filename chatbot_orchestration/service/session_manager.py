"""
Session State Management for Chatbot Orchestration
Handles session state, caching, and metadata management
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
        """Retrieve session metadata from database."""
        logger.info(f"🔍 Retrieving session metadata for session: {session_id}")

        try:
            metadata = await self.chat_dao.get_session_metadata(session_id)
            if metadata:
                logger.info(f"✅ Retrieved session metadata: {metadata}")
                return metadata
            else:
                logger.warning(f"⚠️ No metadata found for session: {session_id}")
                return {}
        except Exception as e:
            logger.error(f"❌ Error retrieving session metadata: {e}")
            return {}

    async def get_cached_content_id(self, session_id: str) -> Optional[str]:
        """Get cached content ID for a session."""
        try:
            metadata = await self.get_session_metadata(session_id)
            cached_content_id = metadata.get('cached_content_id')
            
            if cached_content_id:
                logger.info(f"✅ Found cached content ID: {cached_content_id}")
                return cached_content_id
            else:
                logger.info(f"ℹ️ No cached content ID found for session: {session_id}")
                return None
        except Exception as e:
            logger.error(f"❌ Error getting cached content ID: {e}")
            return None

    
    async def _save_cache_to_session_background(self, session_id: str, cached_content_id: str):
        """Save cache ID to session in background."""
        try:
            await asyncio.sleep(0.1)  # Small delay to ensure cache is created
            
            metadata = {
                'cached_content_id': cached_content_id,
                'cache_created_at': datetime.utcnow().isoformat(),
                'cache_expires_at': (datetime.utcnow() + timedelta(hours=1)).isoformat()
            }
            
            # Update session with cache info (use update_session_cache_info from chat_dao)
            await self.chat_dao.update_session_cache_info(session_id, cached_content_id)
            logger.info(f"✅ Saved cache ID to session: {session_id}")
            
        except Exception as e:
            logger.error(f"❌ Failed to save cache to session: {e}")

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
        """Get chat history - delegates to chat_dao."""
        result = await self.chat_dao.get_chat_history(session_id)
        return result.get("messages", []) if result else []

    async def save_message(self, session_id: str, role: str, content: str, metadata: Dict[str, Any] = None):
        """
        Save message to database with lazy session creation.
        
        Session is created ONLY when the first message arrives (lazy creation).
        This prevents empty sessions from cluttering the database.
        """
        try:
            from shared.sqlalchemy_db import get_db_session
            from sqlalchemy import text

            async with get_db_session() as session:
                # First, get or create the session integer ID (LAZY CREATION)
                session_query = """
                    SELECT id FROM chat_sessions WHERE session_id = :session_id
                """
                result = await session.execute(text(session_query), {"session_id": session_id})
                session_record = result.mappings().first()

                if not session_record:
                    # Create session ONLY when first message arrives (lazy creation)
                    logger.info(f"🆕 Creating new session {session_id} (first message received)")
                    create_session_query = """
                        INSERT INTO chat_sessions (session_id, started_at, last_activity_at, is_active, message_count, archive_status)
                        VALUES (:session_id, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, true, 0, 'active')
                        RETURNING id
                    """
                    result = await session.execute(text(create_session_query), {"session_id": session_id})
                    session_record = result.mappings().first()
                    await session.commit()
                    logger.info(f"✅ Session {session_id} created with ID {session_record['id']}")

                integer_session_id = session_record["id"]

                # Insert message with integer session_id
                insert_query = """
                    INSERT INTO chat_messages (session_id, role, content, created_at)
                    VALUES (:session_id, :role, :content, CURRENT_TIMESTAMP)
                    RETURNING id, session_id, role, content, created_at
                """
                result = await session.execute(
                    text(insert_query),
                    {"session_id": integer_session_id, "role": role, "content": content}
                )
                record = result.mappings().first()
                
                # Increment message count
                update_count_query = """
                    UPDATE chat_sessions 
                    SET message_count = message_count + 1,
                        last_activity_at = CURRENT_TIMESTAMP
                    WHERE id = :session_id
                """
                await session.execute(text(update_count_query), {"session_id": integer_session_id})
                
                await session.commit()

                logger.debug(f"💾 Saved {role} message to session {session_id} (DB ID: {integer_session_id})")

                message_data = {
                    "id": record["id"],
                    "session_id": record["session_id"],
                    "role": record["role"],
                    "content": record["content"],
                    "created_at": record["created_at"].isoformat() if record["created_at"] else None
                }

                # Broadcast messages to agents in real-time via Redis Pub/Sub
                if role in ["user", "assistant"]:
                    try:
                        from shared.redis_pubsub_manager import broadcast_event_for_session
                        
                        # Check if session is assigned to an agent
                        assignment_query = """
                            SELECT assignee_email FROM session_assignments 
                            WHERE session_id = :session_id AND status = 'active'
                        """
                        assignment_result = await session.execute(
                            text(assignment_query), 
                            {"session_id": integer_session_id}
                        )
                        assignment = assignment_result.mappings().first()
                        assigned_agent = assignment["assignee_email"] if assignment else None
                        
                        # Broadcast to session channel (customer) and agent channel (if assigned)
                        event_data = {
                            "type": "customer_message" if role == "user" else "agent_message",
                            "message_id": str(record["id"]),
                            "session_id": session_id,
                            "text": content,
                            "sender": "customer" if role == "user" else "assistant",
                            "timestamp": record["created_at"].isoformat() if record["created_at"] else None
                        }
                        
                        await broadcast_event_for_session(session_id, event_data, assigned_agent)
                        logger.info(f"📤 Broadcasted {role} message to session {session_id} and agent {assigned_agent}")
                    except Exception as broadcast_error:
                        logger.warning(f"⚠️ Failed to broadcast {role} message: {broadcast_error}")
                        # Don't fail the save operation if broadcast fails

                return message_data
        except Exception as e:
            logger.error(f"Error saving message: {e}")
            return None

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
            logger.info(f"🗑️ Cleaned up expired session: {session_id}")

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
        # This is a synchronous wrapper - returns empty list
        # For actual history, use async get_chat_history
        return []

    def update_session_state(self, session_id: str, result: Any) -> Dict[str, Any]:
        """Update session state with result from agent."""
        state = self.get_session_state(session_id)
        state['last_result'] = result
        state['last_activity'] = time.time()
        return state

# Global session manager instance
session_state_manager = SessionStateManager()
