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
            # Get total used tokens from log table
            used = await self.token_dao.get_gemini_usage_from_log()
            
            # Get limit from llm_providers table
            limit = await self.token_dao.get_gemini_limit()
            available = max(0, limit - used)
            
            return {
                'used': used,
                'limit': limit,
                'available': available,
                'percentage': round((used / limit * 100), 2) if limit > 0 else 0
            }
        except Exception as e:
            logger.error(f"Error fetching Gemini usage: {e}")
            raise
    
    async def get_detailed_token_usage(self, limit: int = 50, provider: str = None, api_call_type: str = None) -> dict:
        """Get detailed token usage log with correlations to specific requests."""
        try:
            # Get detailed usage
            rows = await self.token_dao.get_detailed_token_usage(
                provider=provider,
                api_call_type=api_call_type,
                limit=limit
            )
            
            # Format the results
            detailed_usage = []
            for row in rows:
                detailed_usage.append({
                    'id': str(row['id']),
                    'provider': row['provider'],
                    'model': row['model'],
                    'api_call_type': row['api_call_type'],
                    'prompt_tokens': row['prompt_tokens'],
                    'completion_tokens': row['completion_tokens'],
                    'total_tokens': row['total_tokens'],
                    'cache_read_tokens': row['cache_read_tokens'],
                    'cache_write_tokens': row['cache_write_tokens'],
                    'created_at': row['created_at'].isoformat() if row['created_at'] else None
                })
            
            return {
                'success': True,
                'usage': detailed_usage,
                'count': len(detailed_usage)
            }
        except Exception as e:
            logger.error(f"Error getting detailed token usage: {e}")
            raise
