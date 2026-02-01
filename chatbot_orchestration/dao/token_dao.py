"""
Token Data Access Object for Chatbot Orchestration
Handles database operations for token usage tracking
"""

from chatbot_orchestration.core.otel_logger import get_otel_logger

logger = get_otel_logger("token_dao", "chatbot-orchestration")

class TokenDAO:
    """Data access object for token operations"""
    
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection
