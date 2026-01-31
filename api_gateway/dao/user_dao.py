from typing import Any, Dict, List, Optional

from api_gateway.core.db import get_db_connection
from api_gateway.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class UserDAO:
    """Shared DAO for user-related operations across all services."""
    
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection
