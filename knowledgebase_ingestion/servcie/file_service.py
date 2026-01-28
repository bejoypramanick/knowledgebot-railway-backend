"""
File Service Layer for Knowledgebase Ingestion
Provides business logic for file operations
"""
import logging
from typing import Optional, Dict, Any
from ..dao.file_dao import FileDAO

logger = logging.getLogger(__name__)

class FileService:
    """Service layer for file operations"""
    
    def __init__(self):
        self.file_dao = FileDAO()  # Service manages its own DAO
    
    async def get_or_create_user(self, email: str) -> str:
        """Get user identifier for tracking purposes."""
        if not email:
            logger.warning("No email provided for user identification")
            return None
        
        try:
            user_email = await self.file_dao.get_user_by_email(email)
            return user_email if user_email else email
        except Exception as e:
            logger.error(f"Error checking user tables for email {email}: {e}")
            return email

    async def record_api_usage(
        self,
        user_id: Optional[str],
        provider: str,
        endpoint: str,
        method: str = "POST",
        status_code: int = 200,
        req_size: int = 0,
        res_size: int = 0,
        duration_ms: int = 0,
        metadata: Dict[str, Any] = None
    ):
        """Record API usage to the database."""
        try:
            await self.file_dao.record_api_usage(
                user_id, provider, endpoint, method, status_code,
                req_size, res_size, duration_ms, metadata
            )
        except Exception as e:
            logger.exception("Failed to record API usage: %s", e)

    async def check_duplicate_file(self, sha256_hash: str, original_filename: str) -> Optional[Dict[str, Any]]:
        """Check if a file with the same hash or name already exists."""
        try:
            # Check by hash first (exact duplicate)
            existing = await self.file_dao.find_duplicate_by_hash(sha256_hash)
            if existing:
                return {
                    "id": str(existing['id']),
                    "original_filename": existing['original_filename'],
                    "display_name": existing['display_name'],
                    "sha256_hash": existing['sha256_hash'],
                    "size_bytes": existing['size_bytes'],
                    "gemini_file_name": existing['gemini_file_name'],
                    "version": existing['version'],
                    "match_type": "hash"
                }
            
            # Check by filename (same name, different content)
            existing_by_name = await self.file_dao.find_duplicate_by_name(original_filename)
            if existing_by_name:
                return {
                    "id": str(existing_by_name['id']),
                    "original_filename": existing_by_name['original_filename'],
                    "display_name": existing_by_name['display_name'],
                    "sha256_hash": existing_by_name['sha256_hash'],
                    "size_bytes": existing_by_name['size_bytes'],
                    "gemini_file_name": existing_by_name['gemini_file_name'],
                    "version": existing_by_name['version'],
                    "match_type": "filename"
                }
            
            return None
        except Exception as e:
            logger.warning(f"Error checking for duplicate file: {e}")
            return None

    async def delete_existing_file_record(self, db_id: str):
        """Delete an existing file record from database."""
        try:
            await self.file_dao.delete_file_record(db_id)
            logger.info(f"Deleted old file record from database: {db_id}")
        except Exception as e:
            logger.error(f"Error deleting existing file record: {e}")

    async def record_metadata(self, user_id: str, original_filename: str, file_display_name: str, 
                             file_ext: str, uploaded_file: Any, 
                             file_size: int, sha256_hash: str, 
                             final_state: str, gemini_processed_at: Any, mime_type: str, version: int = 1):
        """Persist file metadata and metrics to the PostgreSQL database."""
        try:
            logger.info(f"🗄️ [DB] Saving metadata for {original_filename} (version {version})")
            
            record_data = {
                'user_id': user_id,
                'original_filename': original_filename,
                'display_name': file_display_name,
                'file_ext': file_ext.lstrip('.'),
                'gemini_file_name': uploaded_file.name,
                'gemini_file_uri': getattr(uploaded_file, 'uri', None),
                'mime_type': mime_type,
                'file_size': file_size,
                'sha256_hash': sha256_hash,
                'status': final_state.lower(),
                'state': final_state,
                'processed_at': gemini_processed_at,
                'expires_at': uploaded_file.expiration_time if hasattr(uploaded_file, 'expiration_time') else None,
                'metadata': {'gemini_file_id': uploaded_file.name},
                'version': version
            }
            
            db_record_id = await self.file_dao.insert_file_record(record_data)
            logger.info(f"✅ [DB] Record created with ID: {db_record_id} (version {version})")
            
            # Log metric
            await self.file_dao.record_metric({
                'type': 'file_upload',
                'name': 'file_size_bytes',
                'value': file_size,
                'unit': 'bytes',
                'user_id': user_id,
                'file_id': db_record_id,
                'metadata': {'filename': original_filename}
            })
            
            return db_record_id
        except Exception as e:
            logger.error(f"❌ [DB] Error recording metadata: {e}")
            raise
