"""
Token Usage Service for Configuration Service
Provides business logic layer for token usage tracking operations
"""
from typing import Any, Dict, List, Optional
from datetime import datetime

from shared.otel_logger import get_otel_logger
from configuration.dao.token_dao import TokenDAO

logger = get_otel_logger("token_usage_service", "configuration")


class TokenUsageService:
    """Service layer for token usage operations"""

    def __init__(self):
        self._token_dao = TokenDAO()

    async def get_token_usage(
        self,
        start_date: Optional[datetime] = None,
        end_date: Optional[datetime] = None
    ) -> List[Dict[str, Any]]:
        """Get token usage for a date range"""
        try:
            return await self._token_dao.get_token_usage(start_date, end_date)
        except Exception as e:
            logger.error(f"Error getting token usage: {e}")
            raise

    async def get_token_summary(self) -> Dict[str, Any]:
        """Get token usage summary"""
        try:
            return await self._token_dao.get_token_summary()
        except Exception as e:
            logger.error(f"Error getting token summary: {e}")
            raise

    async def get_detailed_token_usage(
        self,
        limit: int = 100,
        provider: Optional[str] = None,
        api_call_type: Optional[str] = None
    ) -> List[Dict]:
        """Get detailed token usage log"""
        try:
            return await self._token_dao.get_detailed_token_usage(limit, provider, api_call_type)
        except Exception as e:
            logger.error(f"Error getting detailed token usage: {e}")
            raise
