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
            usage_data.get('api_call_type')
        )
