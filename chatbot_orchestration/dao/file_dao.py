"""
File Data Access Object for Chatbot Orchestration
Handles database operations for file management
"""

from chatbot_orchestration.core.db import get_db_connection
from chatbot_orchestration.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class FileDAO:
    """Data access object for file operations"""
    
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection
