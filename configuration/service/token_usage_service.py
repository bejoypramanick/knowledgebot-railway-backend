"""
Token Usage Service Layer
Provides business logic for token usage management operations
"""
from typing import Optional

from shared.dao.token_dao import TokenDAO
from shared.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class TokenUsageService:
    """Service layer for token usage management"""
    
    def __init__(self):
        self.token_dao = TokenDAO()  # Service manages its own DAO
    
    async def get_gemini_usage(self) -> dict:
        """Get Gemini API token usage by calculating totals from token_usage_log table."""
        logger.info(" get_gemini_usage called")
        try:
            return await self.token_dao.get_gemini_usage()
        except Exception as e:
            logger.error(f"Error fetching Gemini usage: {e}")
            raise

    async def get_detailed_token_usage(self, limit: int = 50, provider: str = None, api_call_type: str = None) -> dict:
        """Get detailed token usage log with correlations to specific requests."""
        logger.info(" get_detailed_token_usage called")
        try:
            return await self.token_dao.get_detailed_token_usage(limit, provider, api_call_type)
        except Exception as e:
            logger.error(f"Error getting detailed token usage: {e}")
            raise

    async def track_token_usage(self, session_id: str, message_id: str, provider: str, model: str, 
                               prompt_tokens: int, completion_tokens: int, total_tokens: int, 
                               api_call_type: str, request_metadata: Optional[dict] = None):
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
