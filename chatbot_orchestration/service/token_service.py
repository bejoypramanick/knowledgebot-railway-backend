"""
Token Service Layer for Chatbot Orchestration
Provides business logic for token usage tracking
"""

from shared.otel_logger import get_otel_logger
from chatbot_orchestration.dao.token_dao import TokenDAO

logger = get_otel_logger("token_service", "chatbot-orchestration")

class TokenService:
    """Service layer for token usage tracking"""
    
    def __init__(self):
        self._token_dao = TokenDAO()

    async def track_token_usage(
        self,
        session_id: str,
        message_id: str,
        provider: str,
        model: str,
        prompt_tokens: int,
        completion_tokens: int,
        total_tokens: int,
        api_call_type: str = None,
        request_metadata: dict = None
    ) -> bool:
        """Track token usage using the TokenDAO"""
        logger.info(f"🔍 TokenService.track_token_usage called - session: {session_id}, total_tokens: {total_tokens}")
        try:
            result = await self._token_dao.save_token_usage(
                session_id=session_id,
                message_id=message_id,
                provider=provider,
                model=model,
                prompt_tokens=prompt_tokens,
                completion_tokens=completion_tokens,
                total_tokens=total_tokens,
                api_call_type=api_call_type,
                request_metadata=request_metadata
            )
            logger.info(f"✅ TokenService.track_token_usage completed - result: {result}")
            return result
        except Exception as e:
            logger.error(f"❌ Error tracking token usage: {e}", exc_info=True)
            return False
