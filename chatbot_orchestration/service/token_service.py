"""
Token Service for Token Tracking
Provides business logic layer for token operations
"""
from typing import Any, Dict, Optional

from chatbot_orchestration.dao.token_dao import TokenDAO
from chatbot_orchestration.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class TokenService:
    """Service layer for token operations"""
    
    def __init__(self, token_dao: Optional[TokenDAO] = None):
        self.token_dao = token_dao or TokenDAO()  # Create DAO if not provided
    
    async def update_llm_provider_tokens(self, provider: str, model: str, prompt_tokens: int, completion_tokens: int, total_tokens: int):
        """Update LLM provider token usage"""
        try:
            await self.token_dao.update_llm_provider_tokens(provider, model, prompt_tokens, completion_tokens, total_tokens)
        except Exception as e:
            logger.error(f"Error updating LLM provider tokens: {e}")
    
    async def log_token_usage(self, session_id: str, message_id: str, provider: str, model: str, 
                             prompt_tokens: int, completion_tokens: int, total_tokens: int, 
                             api_call_type: str, request_metadata: Dict[str, Any] = None):
        """Log detailed token usage"""
        try:
            await self.token_dao.log_token_usage(session_id, message_id, provider, model, 
                                   prompt_tokens, completion_tokens, total_tokens, 
                                   api_call_type, request_metadata)
        except Exception as e:
            logger.error(f"Error logging token usage: {e}")
    
    async def track_token_usage(self, session_id: str, message_id: str, provider: str, model: str, 
                               prompt_tokens: int, completion_tokens: int, total_tokens: int, 
                               api_call_type: str, request_metadata: Optional[Dict[str, Any]] = None):
        """Track token usage using the TokenDAO"""
        try:
            await self.token_dao.log_token_usage(
                session_id, message_id, provider, model,
                prompt_tokens, completion_tokens, total_tokens,
                api_call_type, request_metadata
            )
        except Exception as e:
            logger.error(f"Error tracking token usage: {e}")
            raise
