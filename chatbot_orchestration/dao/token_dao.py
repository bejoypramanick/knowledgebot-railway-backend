"""
Token Data Access Object for Chatbot Orchestration
Handles database operations for token usage tracking
"""

from chatbot_orchestration.core.db import get_db_connection
from chatbot_orchestration.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class TokenDAO:
    """Data access object for token operations"""
    
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection
