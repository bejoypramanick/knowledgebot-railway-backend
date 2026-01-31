"""
Token Data Access Object for API Gateway
Handles database operations for token usage tracking
"""

from api_gateway.core.db import get_db_connection
from api_gateway.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class TokenDAO:
    """Data access object for token operations"""
    
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection
