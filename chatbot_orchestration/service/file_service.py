"""
File Service Layer for Chatbot Orchestration
Provides business logic for file operations
"""

from shared.otel_logger import get_otel_logger

logger = get_otel_logger("file_service", "chatbot-orchestration")

class FileService:
    """Service layer for file operations"""
    
    def __init__(self):
        pass  # Service manages its own dependencies
