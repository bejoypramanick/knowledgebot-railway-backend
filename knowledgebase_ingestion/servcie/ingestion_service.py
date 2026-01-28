"""
Ingestion Service Layer
Provides business logic for file ingestion operations
"""
import logging
from typing import List, Optional, Dict, Any
from ..dao.file_dao import FileDAO

logger = logging.getLogger(__name__)

class IngestionService:
    """Service layer for file ingestion"""
    
    def __init__(self):
        self.file_dao = FileDAO()  # Service manages its own DAO
    
    async def process_file_upload(self, file_data: Dict[str, Any], user_email: str) -> Dict[str, Any]:
        """Process single file upload"""
        try:
            # Check for duplicate file
            from .file_service import FileService
            file_service = FileService()
            duplicate = await file_service.check_duplicate_file(file_data['sha256'], user_email)
            if duplicate:
                return {"success": False, "message": "Duplicate file", "file_id": duplicate['id']}
            
            # Record file metadata
            file_id = await self.file_dao.record_file_metadata(file_data, user_email)
            logger.info(f"File uploaded successfully: {file_id}")
            return {"success": True, "file_id": file_id, "message": "File uploaded successfully"}
        except Exception as e:
            logger.error(f"Error processing file upload: {e}")
            raise
    
    async def delete_file(self, file_id: str, user_email: str) -> bool:
        """Delete a file"""
        try:
            await self.file_dao.delete_file_record(file_id, user_email)
            logger.info(f"File deleted successfully: {file_id}")
            return True
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            raise
    
    async def get_user_files(self, user_email: str, limit: int = 50) -> List[Dict[str, Any]]:
        """Get user's files"""
        try:
            return await self.file_dao.get_user_files(user_email, limit)
        except Exception as e:
            logger.error(f"Error fetching user files: {e}")
            raise
