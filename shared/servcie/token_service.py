"""
Token Service for Token Tracking
Provides business logic layer for token operations
"""
import logging
from typing import Dict, Any, Optional
from shared.dao.token_dao import TokenDAO
from shared.db import get_db_connection

logger = logging.getLogger(__name__)

class TokenService:
    """Service layer for token operations"""
    
    def __init__(self):
        self._dao = None
    
    async def _get_dao(self) -> TokenDAO:
        """Get DAO instance with database connection"""
        if self._dao is None:
            async with get_db_connection() as conn:
                self._dao = TokenDAO(conn)
        return self._dao
    
    async def update_llm_provider_tokens(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int, total_tokens: int):
        """Update LLM provider token usage"""
        try:
            dao = await self._get_dao()
            await dao.update_llm_provider_tokens(provider, model, prompt_tokens, completion_tokens, total_tokens)
        except Exception as e:
            logger.error(f"Error updating LLM provider tokens: {e}")
    
    async def log_token_usage(self, session_id: str, message_id: str, provider: str, model: str, 
                             prompt_tokens: int, completion_tokens: int, total_tokens: int, 
                             api_call_type: str, request_metadata: Dict[str, Any] = None):
        """Log detailed token usage"""
        try:
            dao = await self._get_dao()
            await dao.log_token_usage(session_id, message_id, provider, model, 
                                   prompt_tokens, completion_tokens, total_tokens, 
                                   api_call_type, request_metadata)
        except Exception as e:
            logger.error(f"Error logging token usage: {e}")

# Singleton instance
token_service = TokenService()
