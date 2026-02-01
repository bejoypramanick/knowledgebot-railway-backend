"""
Token Data Access Object for Chatbot Orchestration
Handles database operations for token usage tracking
"""

from chatbot_orchestration.core.db import get_db_connection
from chatbot_orchestration.core.otel_logger import get_otel_logger

logger = get_otel_logger("token_dao", "chatbot-orchestration")

class TokenDAO:
    """Data access object for token operations"""
    
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_token_usage(self, session_id: str) -> List[Dict[str, Any]]:
        """Get token usage for a session"""
        query = "SELECT * FROM token_usage WHERE session_id = $1 ORDER BY created_at DESC"
        try:
            async with get_db_connection() as conn:
                result = await conn.fetch(query, session_id)
                logger.log_db_query(query, {"session_id": session_id}, result)
                return [dict(row) for row in result]
        except Exception as e:
            logger.log_db_query(query, {"session_id": session_id}, error=e)
            return []
