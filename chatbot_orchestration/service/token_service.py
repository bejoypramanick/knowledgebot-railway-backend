"""
Token Service Layer for Chatbot Orchestration
Provides business logic for token usage tracking
"""

from chatbot_orchestration.core.otel_logger import get_otel_logger

logger = get_otel_logger("token_service", "chatbot-orchestration")

class TokenService:
    """Service layer for token usage tracking"""
    
    def __init__(self):
        pass  # Service manages its own dependencies
