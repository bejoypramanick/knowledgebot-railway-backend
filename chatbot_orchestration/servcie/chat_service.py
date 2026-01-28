"""
Chat Service Layer for Chatbot Orchestration
Provides business logic for chat operations
"""
import logging
from typing import List, Dict, Any, Optional
from ..dao.chat_dao import ChatDAO

logger = logging.getLogger(__name__)

class ChatService:
    """Service layer for chat operations"""
    
    def __init__(self, chat_dao: ChatDAO):
        self.chat_dao = chat_dao
    
    async def get_session_metadata(self, session_id: str) -> Dict[str, Any]:
        """Get session metadata"""
        try:
            session_data = await self.chat_dao.get_session_metadata(session_id)
            
            if not session_data:
                return {'session_id': session_id, 'is_new_session': True}
            
            return {
                'session_id': session_id,
                'file_search_store_id': session_data['file_search_store_id'],
                'cached_content_id': session_data['cached_content_id'],
                'is_new_session': False
            }
        except Exception as e:
            logger.error(f"Error retrieving session metadata: {e}")
            return {'session_id': session_id, 'is_new_session': True}
    
    async def create_session_metadata(self, session_id: str, file_search_store_id: str, cached_content_id: str) -> None:
        """Create session metadata"""
        try:
            await self.chat_dao.create_session_metadata(session_id, file_search_store_id, cached_content_id)
        except Exception as e:
            logger.error(f"Error creating session metadata: {e}")
            raise
    
    async def get_recent_files(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent files from chat sessions"""
        try:
            return await self.chat_dao.get_recent_files(limit=limit)
        except Exception as e:
            logger.error(f"Error getting recent files: {e}")
            return []
    
    async def update_session_metadata(self, session_id: str, file_search_store_id: str = None, cached_content_id: str = None):
        """Update session metadata"""
        try:
            await self.chat_dao.update_session_metadata(session_id, file_search_store_id, cached_content_id)
        except Exception as e:
            logger.error(f"Error updating session metadata: {e}")
            raise
