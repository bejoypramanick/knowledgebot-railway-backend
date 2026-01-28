import logging
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

class TokenDAO:
    def __init__(self, connection):
        self.conn = connection

    async def update_llm_usage(self, provider: str, total_tokens: int, default_limit: int = 20000):
        """Update token usage for an LLM provider."""
        await self.conn.execute(
            """
            INSERT INTO llm_providers (provider_name, token_used, token_limit, is_active)
            VALUES ($1, $2, $3, true)
            ON CONFLICT (provider_name) DO UPDATE
            SET token_used = COALESCE(llm_providers.token_used, 0) + $2,
                token_limit = COALESCE(llm_providers.token_limit, $3),
                is_active = true
            """,
            provider, total_tokens, default_limit
        )

    async def get_current_usage(self, provider: str) -> int:
        """Get current token usage for a provider."""
        val = await self.conn.fetchval(
            "SELECT COALESCE(token_used, 0) FROM llm_providers WHERE provider_name = $1",
            provider
        )
        return val or 0

    async def insert_usage_log(self, usage_data: Dict[str, Any]):
        """Log detailed token usage."""
        log_query = """
            INSERT INTO token_usage_log (
                session_id, message_id, provider, model, prompt_tokens, completion_tokens,
                total_tokens, cache_read_tokens, cache_write_tokens, api_call_type, created_at
            )
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, NOW())
        """
        await self.conn.execute(
            log_query,
            usage_data.get('session_id'),
            usage_data.get('message_id'),
            usage_data['provider'],
            usage_data['model'],
            usage_data['prompt_tokens'],
            usage_data['completion_tokens'],
            usage_data['total_tokens'],
            usage_data.get('cache_read_tokens', 0),
            usage_data.get('cache_write_tokens', 0),
            usage_data['api_call_type']
        )

    async def get_gemini_usage_from_log(self) -> int:
        """Get total Gemini usage from token_usage_log table."""
        result = await self.conn.fetchrow(
            """
            SELECT COALESCE(SUM(total_tokens), 0) as total_used
            FROM token_usage_log
            WHERE provider = 'gemini'
            """
        )
        return result['total_used'] or 0

    async def get_gemini_limit(self) -> int:
        """Get Gemini token limit from llm_providers table."""
        result = await self.conn.fetchrow(
            """
            SELECT token_limit as limit_value
            FROM llm_providers
            WHERE provider_name = 'gemini' AND is_active = true
            """
        )
        return result['limit_value'] if result else 20000

    async def get_detailed_token_usage(self, start_date: Optional[str] = None, end_date: Optional[str] = None,
                                    session_id: Optional[str] = None, model: Optional[str] = None,
                                    api_call_type: Optional[str] = None, limit: int = 100) -> list:
        """Get detailed token usage with filtering."""
        query = """
            SELECT session_id, message_id, provider, model, api_call_type,
                   prompt_tokens, completion_tokens, total_tokens,
                   cache_read_tokens, cache_write_tokens, created_at
            FROM token_usage_log
            WHERE 1=1
        """
        params = []
        
        if start_date:
            query += " AND created_at >= $" + str(len(params) + 1)
            params.append(start_date)
        
        if end_date:
            query += " AND created_at <= $" + str(len(params) + 1)
            params.append(end_date)
        
        if session_id:
            query += " AND session_id = $" + str(len(params) + 1)
            params.append(session_id)
        
        if model:
            query += " AND model = $" + str(len(params) + 1)
            params.append(model)
        
        if api_call_type:
            query += " AND api_call_type = $" + str(len(params) + 1)
            params.append(api_call_type)
        
        query += " ORDER BY created_at DESC LIMIT $" + str(len(params) + 1)
        params.append(limit)
        
        return await self.conn.fetch(query, *params)

    async def initialize_gemini_provider(self) -> None:
        """Initialize Gemini provider in llm_providers table."""
        await self.conn.execute(
            """
            INSERT INTO llm_providers (provider_name, token_limit, token_used, is_active)
            VALUES ('gemini', 20000, 0, true)
            ON CONFLICT (provider_name) DO NOTHING
            """
        )
