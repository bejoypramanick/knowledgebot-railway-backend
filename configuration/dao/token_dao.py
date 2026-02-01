"""
Token Data Access Object for Configuration Service
Handles database operations for token management
"""
from typing import Dict, List, Any, Optional

from configuration.core.db import get_db_connection
from configuration.core.otel_logger import get_otel_logger

logger = get_otel_logger("token_dao", "configuration")

class TokenDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def update_llm_usage(self, provider: str, total_tokens: int, default_limit: int = 20000):
        """Update LLM token usage for a provider."""
        try:
            async with get_db_connection() as conn:
                query = """
                    INSERT INTO llm_providers (provider_name, token_used, token_limit, is_active)
                    VALUES ($1, $2, $3, true)
                    ON CONFLICT (provider_name) DO UPDATE SET
                    token_used = llm_providers.token_used + EXCLUDED.token_used,
                    updated_at = NOW()
                """
                params = [provider, total_tokens, default_limit]
                result = await conn.execute(query, *params)
                logger.log_db_query(query, params, result)
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def log_token_usage(self, session_id: str, message_id: str, provider: str, model: str, 
                             prompt_tokens: int, completion_tokens: int, total_tokens: int, 
                             api_call_type: str, request_metadata: Optional[dict] = None):
        """Log detailed token usage for a specific API call."""
        try:
            async with get_db_connection() as conn:
                query = """
                    INSERT INTO token_usage_log 
                    (session_id, message_id, provider, model, prompt_tokens, completion_tokens, 
                     total_tokens, api_call_type, request_metadata, created_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())
                """
                params = [session_id, message_id, provider, model, prompt_tokens, 
                          completion_tokens, total_tokens, api_call_type, request_metadata]
                result = await conn.execute(query, *params)
                logger.log_db_query(query, params, result)
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def get_gemini_usage(self) -> dict:
        """Get Gemini API token usage by calculating totals from token_usage_log table."""
        try:
            async with get_db_connection() as conn:
                # Get total Gemini usage from token_usage_log
                query = """
                    SELECT 
                        SUM(prompt_tokens) as total_prompt_tokens,
                        SUM(completion_tokens) as total_completion_tokens,
                        SUM(total_tokens) as total_tokens,
                        COUNT(*) as total_requests
                    FROM token_usage_log 
                    WHERE provider = 'gemini'
                """
                result = await conn.fetchrow(query)
                logger.log_db_query(query, {"provider": "gemini"}, result)
                
                if not result:
                    return {
                        "provider": "gemini",
                        "total_prompt_tokens": 0,
                        "total_completion_tokens": 0,
                        "total_tokens": 0,
                        "total_requests": 0
                    }
                
                return {
                    "provider": "gemini",
                    "total_prompt_tokens": result["total_prompt_tokens"] or 0,
                    "total_completion_tokens": result["total_completion_tokens"] or 0,
                    "total_tokens": result["total_tokens"] or 0,
                    "total_requests": result["total_requests"] or 0
                }
        except Exception as e:
            logger.log_db_query("get_gemini_usage", {"provider": "gemini"}, error=e)
            raise

    async def get_detailed_token_usage(self, limit: int = 100, provider: Optional[str] = None, 
                                     api_call_type: Optional[str] = None) -> List[Dict]:
        """Get detailed token usage log with correlations to specific requests."""
        logger.info(" get_detailed_token_usage called")
        try:
            async with get_db_connection() as conn:
                # Build query with optional filters
                query = """
                    SELECT session_id, message_id, provider, model, prompt_tokens, 
                           completion_tokens, total_tokens, api_call_type, 
                           request_metadata, created_at
                    FROM token_usage_log
                """
                params = []
                conditions = []
                
                if provider:
                    conditions.append("provider = $1")
                    params.append(provider)
                if api_call_type:
                    conditions.append("api_call_type = $2")
                    params.append(api_call_type)
                
                if conditions:
                    query += " WHERE " + " AND ".join(conditions)
                
                query += " ORDER BY created_at DESC LIMIT $3"
                params.append(limit)
                
                records = await conn.fetch(query, *params)
                logger.log_db_query(query, {"provider": provider, "api_call_type": api_call_type, "limit": limit}, records)
                return [dict(record) for record in records]
        except Exception as e:
            logger.log_db_query("get_detailed_token_usage", {"provider": provider, "api_call_type": api_call_type, "limit": limit}, error=e)
            raise
