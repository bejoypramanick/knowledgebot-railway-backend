"""
File Data Access Object for Chatbot Orchestration
Handles database operations for file management
"""
from typing import Dict, Any, Optional
from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("file_dao", "chatbot-orchestration")

class FileDAO:
    """Data access object for file operations"""
    
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_file_metadata(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get file metadata from database"""
        query = "SELECT * FROM file_uploads WHERE id = :file_id"
        params = {"file_id": file_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = (await session.execute(text(query), params)).fetchone()
                logger.log_db_query(query, params, result)
                return dict(result._mapping) if result else None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None
