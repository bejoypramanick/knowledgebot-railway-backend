"""
File Service Layer for Chatbot Orchestration
Provides business logic for file operations
"""
import logging
from typing import List, Optional, Dict, Any
import sys
from pathlib import Path

# Add the project root to the path to allow cross-module imports
sys.path.insert(0, str(Path(__file__).parent.parent.parent))
from knowledgebase_ingestion.dao.file_dao import FileDAO

logger = logging.getLogger(__name__)

class FileService:
    """Service layer for file operations"""
    
    def __init__(self):
        self.file_dao = FileDAO()  # Service manages its own DAO
    
    async def get_active_files_count(self) -> int:
        """Get count of active files"""
        try:
            return await self.file_dao.get_active_files_count()
        except Exception as e:
            logger.error(f"Error getting active files count: {e}")
            return 0
    
    async def get_recent_files(self, limit: int = 5) -> List[Dict[str, Any]]:
        """Get recent uploaded files"""
        try:
            return await self.file_dao.get_recent_files(limit)
        except Exception as e:
            logger.error(f"Error getting recent files: {e}")
            return []
    
    async def get_recent_metrics(self, limit: int = 10) -> List[Dict[str, Any]]:
        """Get recent metrics"""
        try:
            return await self.file_dao.get_recent_metrics(limit)
        except Exception as e:
            logger.error(f"Error getting recent metrics: {e}")
            return []
    
    async def get_file_statistics(self) -> Dict[str, Any]:
        """Get file statistics"""
        try:
            count = await self.file_dao.get_active_files_count()
            recent_files = await self.file_dao.get_recent_files(5)
            
            return {
                "total_files": count,
                "recent_files_count": len(recent_files),
                "recent_files": recent_files
            }
        except Exception as e:
            logger.error(f"Error getting file statistics: {e}")
            return {"total_files": 0, "recent_files_count": 0, "recent_files": []}
