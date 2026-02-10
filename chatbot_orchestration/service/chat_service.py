"""
Chat Service Layer for Chatbot Orchestration
Provides utility methods for chat operations (history, sessions)
NOTE: All chat responses use STREAMING ONLY via agent_service.stream_agent_response
"""
from shared.otel_logger import get_otel_logger
from ..service.session_manager import session_state_manager
from ..dao.chat_dao import ChatDAO

logger = get_otel_logger("chat_service", "chatbot-orchestration")

class ChatService:
    """Service layer for chat utility operations (non-streaming only)"""

    def __init__(self):
        self.chat_dao = ChatDAO()

    async def get_chat_history(self, session_id: str):
        """Get chat history for a session from database."""
        try:
            result = await self.chat_dao.get_chat_history(session_id)
            messages = result.get("messages", [])
            return {
                "session_id": session_id,
                "messages": messages,
                "total_messages": len(messages)
            }
        except Exception as e:
            logger.error(f"Error getting chat history for session {session_id}: {e}")
            raise

    async def delete_session(self, session_id: str):
        """Delete a chat session from database."""
        try:
            success = await self.chat_dao.delete_session(session_id)
            if success:
                logger.info(f"✅ Deleted session: {session_id}")
                return {"success": True, "message": "Session deleted successfully"}
            else:
                logger.warning(f"⚠️ Failed to delete session: {session_id}")
                return {"success": False, "message": "Failed to delete session"}
        except Exception as e:
            logger.error(f"Error deleting session {session_id}: {e}")
            raise

    async def get_all_sessions(self):
        """Get all chat sessions from database."""
        try:
            sessions = await self.chat_dao.get_all_sessions()
            return {
                "sessions": sessions,
                "total_sessions": len(sessions)
            }
        except Exception as e:
            logger.error(f"Error getting all sessions: {e}")
            raise

# Singleton instance
chat_service = ChatService()
