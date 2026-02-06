"""
File Data Access Object for Chatbot Orchestration
Handles database operations for file management
"""
from typing import Dict, Any, Optional
from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("file_dao", "chatbot-orchestration")

class FileDAO:
    """Data access object for file operations"""
    
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_file_metadata(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get file metadata from database"""
        query = "SELECT * FROM file_uploads WHERE id = $1"
        params = {"file_id": file_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, file_id)
                logger.log_db_query(query, params, result)
                return dict(result) if result else None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None
