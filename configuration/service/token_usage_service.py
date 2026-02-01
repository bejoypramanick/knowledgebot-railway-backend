"""
Token Usage Service Layer
Provides business logic for token usage management operations
"""
from typing import Optional
import logging

from configuration.dao.token_dao import TokenDAO

logger = logging.getLogger(__name__)

class TokenUsageService:
    """Service layer for token usage management"""
    
    def __init__(self):
        self.token_dao = TokenDAO()  # Service manages its own DAO
    
    async def get_detailed_token_usage(self, limit: int = 50, provider: str = None, api_call_type: str = None) -> dict:
        """Get detailed token usage log with correlations to specific requests."""
        logger.info(" get_detailed_token_usage called")
        try:
            records = await self.token_dao.get_detailed_token_usage(limit, provider, api_call_type)
            # Convert records to list of dicts and wrap in response dict
            usage_data = [dict(record) for record in records]
            return {
                "data": usage_data,
                "total": len(usage_data),
                "limit": limit,
                "provider": provider,
                "api_call_type": api_call_type
            }
        except Exception as e:
            logger.error(f"Error getting detailed token usage: {e}")
            raise
