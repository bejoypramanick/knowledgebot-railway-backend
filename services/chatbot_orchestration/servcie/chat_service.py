"""
Chat Service for Chatbot Orchestration
Provides business logic layer between routers/tools and DAO
"""
import logging
from typing import List, Dict, Any, Optional
from ..dao.chat_dao import ChatDAO
from shared.db import get_db_connection

logger = logging.getLogger(__name__)

class ChatService:
    """Service layer for chat operations"""
    
    def __init__(self):
        self._dao = None
    
    async def _get_dao(self) -> ChatDAO:
        """Get DAO instance with database connection"""
        if self._dao is None:
            async with get_db_connection() as conn:
                self._dao = ChatDAO(conn)
        return self._dao
    
    async def get_recent_files(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent files from chat sessions"""
        try:
            dao = await self._get_dao()
            return await dao.get_recent_files(limit=limit)
        except Exception as e:
            logger.error(f"Error getting recent files: {e}")
            return []
    
    async def get_session_metadata(self, session_id: str) -> Optional[Dict[str, Any]]:
        """Get session metadata"""
        try:
            dao = await self._get_dao()
            return await dao.get_session_metadata(session_id)
        except Exception as e:
            logger.error(f"Error getting session metadata: {e}")
            return None
    
    async def update_session_metadata(self, session_id: str, file_search_store_id: str = None, cached_content_id: str = None):
        """Update session metadata"""
        try:
            dao = await self._get_dao()
            await dao.update_session_metadata(session_id, file_search_store_id, cached_content_id)
        except Exception as e:
            logger.error(f"Error updating session metadata: {e}")

# Singleton instance
chat_service = ChatService()
