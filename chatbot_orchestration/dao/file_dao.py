"""
File Data Access Object for Chatbot Orchestration
Handles database operations for file management
"""

from chatbot_orchestration.core.otel_logger import get_otel_logger

logger = get_otel_logger("file_dao", "chatbot-orchestration")

class FileDAO:
    """Data access object for file operations"""
    
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection
