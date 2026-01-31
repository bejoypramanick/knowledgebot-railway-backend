"""
File Service Layer for Chatbot Orchestration
Provides business logic for file operations
"""
from typing import Dict, Any, List

from chatbot_orchestration.dao.file_dao import FileDAO
from chatbot_orchestration.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class FileService:
    """Service layer for file operations"""
    
    def __init__(self):
        self.file_dao = FileDAO()  # Service manages its own DAO
