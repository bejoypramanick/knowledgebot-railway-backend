"""
Token Usage Service Layer
Provides business logic for token usage management operations
"""
import logging
from typing import List, Optional, Dict, Any
from shared.dao.token_dao import TokenDAO

logger = logging.getLogger(__name__)

class TokenUsageService:
    """Service layer for token usage management"""
    
    def __init__(self, token_dao: TokenDAO):
        self.token_dao = token_dao
    
    async def get_gemini_usage(self) -> dict:
        """Get Gemini API token usage by calculating totals from token_usage_log table."""
        logger.info(" get_gemini_usage called")
        try:
            return await self.token_dao.get_gemini_usage()
        except Exception as e:
            logger.error(f"Error fetching Gemini usage: {e}")
            raise
