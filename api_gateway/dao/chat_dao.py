"""
Chat Data Access Object for API Gateway
Handles database operations for chat sessions and messages
"""

from api_gateway.core.db import get_db_connection
from api_gateway.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class ChatDAO:
    """Data access object for chat operations"""
    
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection
