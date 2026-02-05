"""
Token Data Access Object for Chatbot Orchestration
Handles database operations for token usage tracking
"""
from typing import List, Dict, Any

from chatbot_orchestration.core.db import get_db_connection
from chatbot_orchestration.core.otel_logger import get_otel_logger

logger = get_otel_logger("token_dao", "chatbot-orchestration")

class TokenDAO:
    """Data access object for token operations"""
    
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def save_token_usage(self, session_id: str, message_id: str, provider: str, model: str, 
                               prompt_tokens: int, completion_tokens: int, total_tokens: int,
                               api_call_type: str = None, request_metadata: dict = None) -> bool:
        """Save token usage record"""
        # First get the integer session ID from string session_id
        session_query = "SELECT id FROM chat_sessions WHERE session_id = $1"
        
        # Get integer message ID from string message_id
        message_query = "SELECT id FROM chat_messages WHERE id = $1"
        
        try:
            async with get_db_connection() as conn:
                # Get integer session ID
                session_record = await conn.fetchrow(session_query, session_id)
                integer_session_id = session_record["id"] if session_record else None
                
                # Get integer message ID
                message_record = await conn.fetchrow(message_query, int(message_id)) if message_id else None
                integer_message_id = message_record["id"] if message_record else None
                
                # Insert token usage record
                query = """
                    INSERT INTO token_usage_log (
                        session_id, message_id, provider, model, prompt_tokens, 
                        completion_tokens, total_tokens, api_call_type, request_metadata
                    ) VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9)
                """
                
                await conn.execute(
                    query, 
                    integer_session_id, 
                    integer_message_id, 
                    provider, 
                    model, 
                    prompt_tokens, 
                    completion_tokens, 
                    total_tokens, 
                    api_call_type, 
                    request_metadata
                )
                
                logger.info(f"✅ Saved token usage: {total_tokens} tokens for session {session_id}")
                return True
                
        except Exception as e:
            logger.error(f"❌ Error saving token usage: {e}")
            return False

    async def get_token_usage(self, session_id: str) -> List[Dict[str, Any]]:
        """Get token usage for a session"""
        # First get the integer session ID from string session_id
        session_query = "SELECT id FROM chat_sessions WHERE session_id = $1"
        
        try:
            async with get_db_connection() as conn:
                # Get integer session ID
                session_record = await conn.fetchrow(session_query, session_id)
                if not session_record:
                    logger.info(f"Session not found for token usage: {session_id}")
                    return []
                
                integer_session_id = session_record["id"]
                
                # Query token usage log table
                query = """
                    SELECT id, session_id, message_id, provider, model, prompt_tokens, 
                           completion_tokens, total_tokens, cost_cents, api_call_type, 
                           request_metadata, created_at, updated_at
                    FROM token_usage_log 
                    WHERE session_id = $1 
                    ORDER BY created_at DESC
                """
                
                result = await conn.fetch(query, integer_session_id)
                logger.log_db_query(query, {"session_id": integer_session_id}, result)
                return [dict(row) for row in result]
        except Exception as e:
            logger.log_db_query(session_query, {"session_id": session_id}, error=e)
            return []
