"""
Chat Log Data Access Object for Configuration Service
Handles database operations for chat logging
"""

from configuration.core.db import get_db_connection
from configuration.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class ChatLogDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection
