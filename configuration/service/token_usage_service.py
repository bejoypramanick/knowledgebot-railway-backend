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

    async def record_token_usage(
        self,
        provider: str,
        tokens_used: int,
        session_id: Optional[str] = None
    ) -> bool:
        """Record token usage"""
        try:
            await self._token_dao.record_token_usage(provider, tokens_used, session_id)
            return True
        except Exception as e:
            logger.error(f"Error recording token usage: {e}")
            raise
