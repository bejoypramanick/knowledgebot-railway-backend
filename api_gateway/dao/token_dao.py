from typing import Any, Dict, List, Optional

from api_gateway.core.db import get_db_connection
from api_gateway.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class TokenDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def update_llm_usage(self, provider: str, total_tokens: int, default_limit: int = 20000):
        """Update LLM token usage for a provider."""
        try:
            async with get_db_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO llm_providers (provider_name, token_used, token_limit, is_active)
                    VALUES ($1, $2, $3, true)
                    ON CONFLICT (provider_name) DO UPDATE SET
                    token_used = llm_providers.token_used + EXCLUDED.token_used,
                    updated_at = NOW()
                    """,
                    provider, total_tokens, default_limit
                )
        except Exception as e:
            logger.error(f"Error updating LLM usage: {e}")
            raise

    async def log_token_usage(self, session_id: str, message_id: str, provider: str, model: str, 
                             prompt_tokens: int, completion_tokens: int, total_tokens: int, 
                             api_call_type: str, request_metadata: Optional[dict] = None):
        """Log detailed token usage for a specific API call."""
        try:
            async with get_db_connection() as conn:
                await conn.execute(
                    """
                    INSERT INTO token_usage_log 
                    (session_id, message_id, provider, model, prompt_tokens, completion_tokens, 
                     total_tokens, api_call_type, request_metadata, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                    """,
                    session_id, message_id, provider, model, prompt_tokens, 
                    completion_tokens, total_tokens, api_call_type, 
                    request_metadata
                )
        except Exception as e:
            logger.error(f"Error logging token usage: {e}")
            raise

    async def get_token_usage_stats(self, provider: str = None) -> List[Dict[str, Any]]:
        """Get token usage statistics."""
        try:
            async with get_db_connection() as conn:
                if provider:
                    return await conn.fetch(
                        """
                        SELECT provider_name, token_used, token_limit, 
                               (token_limit - token_used) as remaining_tokens,
                               updated_at
                        FROM llm_providers 
                        WHERE provider_name = $1 AND is_active = true
                        """,
                        provider
                    )
                else:
                    return await conn.fetch(
                        """
                        SELECT provider_name, token_used, token_limit, 
                               (token_limit - token_used) as remaining_tokens,
                               updated_at
                        FROM llm_providers 
                        WHERE is_active = true
                        ORDER BY provider_name
                        """
                    )
        except Exception as e:
            logger.error(f"Error getting token usage stats: {e}")
            return []

    async def get_daily_token_usage(self, provider: str = None, days: int = 30) -> List[Dict[str, Any]]:
        """Get daily token usage for the last N days."""
        try:
            async with get_db_connection() as conn:
                if provider:
                    return await conn.fetch(
                        """
                        SELECT DATE(created_at) as date, 
                               SUM(total_tokens) as total_tokens,
                               COUNT(*) as api_calls
                        FROM token_usage_log 
                        WHERE provider = $1 AND created_at >= NOW() - INTERVAL '%s days'
                        GROUP BY DATE(created_at)
                        ORDER BY date DESC
                        """ % days,
                        provider
                    )
                else:
                    return await conn.fetch(
                        """
                        SELECT DATE(created_at) as date, 
                               SUM(total_tokens) as total_tokens,
                               COUNT(*) as api_calls
                        FROM token_usage_log 
                        WHERE created_at >= NOW() - INTERVAL '%s days'
                        GROUP BY DATE(created_at)
                        ORDER BY date DESC
                        """ % days
                    )
        except Exception as e:
            logger.error(f"Error getting daily token usage: {e}")
            return []

    async def get_detailed_token_usage(self, limit: int = 50, provider: str = None, api_call_type: str = None) -> List[Dict[str, Any]]:
        """Get detailed token usage records."""
        try:
            async with get_db_connection() as conn:
                query = """
                    SELECT session_id, provider, model, prompt_tokens, completion_tokens, 
                           total_tokens, api_call_type, request_metadata, created_at
                    FROM token_usage_log
                    WHERE 1=1
                """
                params = []
                param_counter = 1
                
                if provider:
                    query += f" AND provider = ${param_counter}"
                    params.append(provider)
                    param_counter += 1
                    
                if api_call_type:
                    query += f" AND api_call_type = ${param_counter}"
                    params.append(api_call_type)
                    param_counter += 1
                
                query += f" ORDER BY created_at DESC LIMIT ${param_counter}"
                params.append(limit)
                
                return await conn.fetch(query, *params)
        except Exception as e:
            logger.error(f"Error getting detailed token usage: {e}")
            return []
