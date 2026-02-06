"""
Token Data Access Object for Chatbot Orchestration
Handles database operations for token usage tracking
"""
from typing import List, Dict, Any, Optional

from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("token_dao", "chatbot-orchestration")

class TokenDAO:
    """Data access object for token operations"""
    
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def save_token_usage(self, session_id: str, message_id: str, provider: str, model: str, 
                               prompt_tokens: int, completion_tokens: int, total_tokens: int,
                               api_call_type: str = None, request_metadata: dict = None) -> bool:
        """Save token usage record"""
        session_query = "SELECT id FROM chat_sessions WHERE session_id = $1"
        try:
            async with get_db_connection() as conn:
                logger.log_db_operation(session_query, session_id)
                session_record = await conn.fetchrow(session_query, session_id)
                logger.log_db_query(session_query, {"session_id": session_id}, session_record)
                
                integer_session_id = session_record["id"] if session_record else None
                integer_message_id = None

                query = """
                    INSERT INTO token_usage_log (
                        session_id, message_id, provider, model, prompt_tokens, 
                        completion_tokens, total_tokens, api_call_type, request_metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """
                params = [integer_session_id, integer_message_id, provider, model, 
                          prompt_tokens, completion_tokens, total_tokens, api_call_type, request_metadata]
                
                logger.log_db_operation(query, params)
                await conn.execute(query, *params)
                logger.log_db_query(query, params, "INSERT 1")
                return True
                
        except Exception as e:
            logger.error(f"❌ Error saving token usage: {e}")
            return False

    async def get_token_usage(self, session_id: str) -> List[Dict[str, Any]]:
        """Get token usage for a session"""
        session_query = "SELECT id FROM chat_sessions WHERE session_id = $1"
        try:
            async with get_db_connection() as conn:
                logger.log_db_operation(session_query, session_id)
                session_record = await conn.fetchrow(session_query, session_id)
                logger.log_db_query(session_query, {"session_id": session_id}, session_record)
                
                if not session_record:
                    return []
                
                integer_session_id = session_record["id"]
                
                query = """
                    SELECT id, session_id, message_id, provider, model, prompt_tokens, 
                           completion_tokens, total_tokens, cost_cents, api_call_type, 
                           request_metadata, created_at, updated_at
                    FROM token_usage_log 
                    WHERE session_id = $1 
                    ORDER BY created_at DESC
                """
                logger.log_db_operation(query, integer_session_id)
                result = await conn.fetch(query, integer_session_id)
                logger.log_db_query(query, {"session_id": integer_session_id}, result)
                return [dict(row) for row in result]
        except Exception as e:
            logger.log_db_query("get_token_usage", {"session_id": session_id}, error=e)
            return []
