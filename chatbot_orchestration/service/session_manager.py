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

    async def get_or_create_cached_content(self, system_prompt: str, tool_functions: list = None) -> str:
        """Get or create cached content for system prompt + tool schemas."""
        logger.info("🚀 Creating cached content for system prompt + tool schemas")

        await self.initialize()
        if not self.genai_client:
            raise RuntimeError("GenAI client not initialized")

        try:
            from google.genai import types

            # Cache ONLY the system prompt (not tools)
            # Tools will be passed to Agent separately to avoid 400 error
            config_params = {
                'system_instruction': system_prompt,
                'ttl': '900s'  # 15 minutes (format: "Ns" for seconds)
            }

            # Create cache with proper API format - use same model as agent
            logger.info(f"🔧 Creating cache for model: models/{MODEL_NAME}")
            cache = self.genai_client.caches.create(
                model=f'models/{MODEL_NAME}',
                config=types.CreateCachedContentConfig(**config_params)
            )

            cached_content_id = cache.name
            logger.info(f"✅ Created cached content: {cached_content_id}")
            logger.info(f"💰 Cached: system prompt only (~32K tokens)")
            logger.info(f"ℹ️ Tools NOT cached - will be passed to Agent separately")
            return cached_content_id

        except Exception as e:
            logger.error(f"❌ Failed to create cached content: {e}")
            raise

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
        """Save message to database."""
        try:
            from shared.db import get_db_connection
            async with get_db_connection() as conn:
                # First, get or create the session integer ID
                session_query = """
                    SELECT id FROM chat_sessions WHERE session_id = $1
                """
                session_record = await conn.fetchrow(session_query, session_id)

                if not session_record:
                    # Create session if it doesn't exist
                    create_session_query = """
                        INSERT INTO chat_sessions (session_id, started_at, last_activity_at, is_active, message_count)
                        VALUES ($1, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP, true, 0)
                        RETURNING id
                    """
                    session_record = await conn.fetchrow(create_session_query, session_id)

                integer_session_id = session_record["id"]

                # Insert message with integer session_id
                insert_query = """
                    INSERT INTO chat_messages (session_id, role, content, created_at)
                    VALUES ($1, $2, $3, CURRENT_TIMESTAMP)
                    RETURNING id, session_id, role, content, created_at
                """
                record = await conn.fetchrow(insert_query, integer_session_id, role, content)

                return {
                    "id": record["id"],
                    "session_id": record["session_id"],
                    "role": record["role"],
                    "content": record["content"],
                    "created_at": record["created_at"].isoformat() if record["created_at"] else None
                }
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
