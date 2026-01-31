"""
Token Service Layer for API Gateway
Provides business logic for token usage tracking
"""
from typing import Optional

from api_gateway.dao.token_dao import TokenDAO
from api_gateway.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class TokenService:
    """Service layer for token usage tracking"""
    
    def __init__(self, token_dao: Optional[TokenDAO] = None):
        self.token_dao = token_dao or TokenDAO()  # Create DAO if not provided
