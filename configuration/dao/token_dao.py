"""
Token Data Access Object for Configuration Service
Handles database operations for token management
"""
from typing import Dict, List, Any, Optional

from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("token_dao", "configuration")

class TokenDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def update_llm_usage(self, provider: str, total_tokens: int, default_limit: int = 20000):
        """Update LLM token usage for a provider."""
        query = """
            INSERT INTO llm_providers (provider_name, token_used, token_limit, is_active)
            VALUES (:provider, :total_tokens, :default_limit, true)
            ON CONFLICT (provider_name) DO UPDATE SET
            token_used = llm_providers.token_used + EXCLUDED.token_used,
            updated_at = NOW()
        """
        params = {"provider": provider, "total_tokens": total_tokens, "default_limit": default_limit}
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def log_token_usage(self, session_id: str, message_id: str, provider: str, model: str,
                             prompt_tokens: int, completion_tokens: int, total_tokens: int,
                             api_call_type: str, request_metadata: Optional[dict] = None):
        """Log detailed token usage for a specific API call."""
        query = """
            INSERT INTO token_usage_log
            (session_id, message_id, provider, model, prompt_tokens, completion_tokens,
             total_tokens, api_call_type, request_metadata, created_at)
            VALUES (:session_id, :message_id, :provider, :model, :prompt_tokens,
                    :completion_tokens, :total_tokens, :api_call_type, :request_metadata, NOW())
        """
        params = {"session_id": session_id, "message_id": message_id, "provider": provider, "model": model, "prompt_tokens": prompt_tokens,
                  "completion_tokens": completion_tokens, "total_tokens": total_tokens, "api_call_type": api_call_type, "request_metadata": request_metadata}
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, None)
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def get_gemini_usage(self) -> dict:
        """Get Gemini API token usage by calculating totals from token_usage_log table."""
        query = """
            SELECT
                SUM(prompt_tokens) as total_prompt_tokens,
                SUM(completion_tokens) as total_completion_tokens,
                SUM(total_tokens) as total_tokens,
                COUNT(*) as total_requests
            FROM token_usage_log
            WHERE provider = 'gemini'
        """
        params = {"provider": "gemini"}
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                row = result.fetchone()
                logger.log_db_query(query, params, row)

                if not row:
                    return {
                        "provider": "gemini",
                        "total_prompt_tokens": 0,
                        "total_completion_tokens": 0,
                        "total_tokens": 0,
                        "total_requests": 0
                    }

                return {
                    "provider": "gemini",
                    "total_prompt_tokens": row["total_prompt_tokens"] or 0,
                    "total_completion_tokens": row["total_completion_tokens"] or 0,
                    "total_tokens": row["total_tokens"] or 0,
                    "total_requests": row["total_requests"] or 0
                }
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            raise

    async def get_detailed_token_usage(self, limit: int = 100, provider: Optional[str] = None,
                                     api_call_type: Optional[str] = None) -> List[Dict]:
        """Get detailed token usage log with correlations to specific requests."""
        try:
            # Build query with optional filters
            query = """
                SELECT session_id, message_id, provider, model, prompt_tokens,
                       completion_tokens, total_tokens, api_call_type,
                       request_metadata, created_at
                FROM token_usage_log
            """
            params = {}
            conditions = []

            if provider:
                conditions.append("provider = :provider")
                params["provider"] = provider
            if api_call_type:
                conditions.append("api_call_type = :api_call_type")
                params["api_call_type"] = api_call_type

            if conditions:
                query += " WHERE " + " AND ".join(conditions)

            query += " ORDER BY created_at DESC LIMIT :limit"
            params["limit"] = limit

            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                records = result.fetchall()
                logger.log_db_query(query, params, records)
                return [dict(row._mapping) for row in records]
        except Exception as e:
            logger.log_db_query("get_detailed_token_usage", {"provider": provider, "api_call_type": api_call_type, "limit": limit}, error=e)
            raise
