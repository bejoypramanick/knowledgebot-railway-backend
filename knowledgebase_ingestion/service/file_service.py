"""
File Service Layer for Knowledgebase Ingestion
Provides business logic for file operations
"""
from typing import Any, Dict, Optional

from shared import db
from shared.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

class FileService:
    """Service layer for file operations"""
    
    def __init__(self):
        pass  # No DAO needed - using direct database calls
    
    async def get_or_create_user(self, email: str) -> str:
        """Get user identifier for tracking purposes."""
        if not email:
            logger.warning("No email provided for user identification")
            return None
        
        try:
            # Simple user lookup - for now just return email
            # In future, could implement user table lookup
            return email
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
            if db.railway_db:
                await db.railway_db.execute(
                    """INSERT INTO api_usage (user_id, provider, endpoint, method, status_code, 
                       req_size, res_size, duration_ms, metadata, created_at) 
                       VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, NOW())""",
                    user_id, provider, endpoint, method, status_code,
                    req_size, res_size, duration_ms, metadata
                )
        except Exception as e:
            logger.exception("Failed to record API usage: %s", e)

    async def check_duplicate_file(self, sha256_hash: str, original_filename: str) -> Optional[Dict[str, Any]]:
        """Check if a file with the same hash or name already exists."""
        try:
            if not db.railway_db:
                return None
                
            # Check by hash first (exact duplicate)
            existing = await db.railway_db.fetchrow(
                "SELECT id, original_filename, display_name, sha256_hash, size_bytes, gemini_file_name, version FROM file_uploads WHERE sha256_hash = $1",
                sha256_hash
            )
            if existing:
                return {
                    "id": str(existing['id']),
                    "original_filename": existing['original_filename'],
                    "display_name": existing['display_name'],
                    "sha256_hash": existing['sha256_hash'],
                    "size_bytes": existing['size_bytes'],
                    "gemini_file_name": existing['gemini_file_name'],
                    "version": existing.get('version', 1),
                    "match_type": "hash"
                }
            
            # Check by filename (same name, different content)
            existing_by_name = await db.railway_db.fetchrow(
                "SELECT id, original_filename, display_name, sha256_hash, size_bytes, gemini_file_name, version FROM file_uploads WHERE original_filename = $1",
                original_filename
            )
            if existing_by_name:
                return {
                    "id": str(existing_by_name['id']),
                    "original_filename": existing_by_name['original_filename'],
                    "display_name": existing_by_name['display_name'],
                    "sha256_hash": existing_by_name['sha256_hash'],
                    "size_bytes": existing_by_name['size_bytes'],
                    "gemini_file_name": existing_by_name['gemini_file_name'],
                    "version": existing_by_name.get('version', 1),
                    "match_type": "filename"
                }
            
            return None
        except Exception as e:
            logger.warning(f"Error checking for duplicate file: {e}")
            return None

    async def delete_existing_file_record(self, db_id: str):
        """Delete an existing file record from database."""
        try:
            if db.railway_db:
                await db.railway_db.execute("DELETE FROM file_uploads WHERE id = $1", db_id)
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
            
            if not db.railway_db:
                logger.warning("Database not available - skipping metadata recording")
                return None
            
            db_record_id = await db.railway_db.fetchval(
                """INSERT INTO file_uploads (user_id, original_filename, display_name, file_extension, 
                   gemini_file_name, gemini_file_uri, mime_type, size_bytes, sha256_hash, 
                   gemini_state, processed_at, version, created_at) 
                   VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12, NOW()) RETURNING id""",
                user_id, original_filename, file_display_name, file_ext.lstrip('.'),
                uploaded_file.name, getattr(uploaded_file, 'uri', None), mime_type,
                file_size, sha256_hash, final_state, gemini_processed_at, version
            )
            
            logger.info(f"✅ [DB] Record created with ID: {db_record_id} (version {version})")
            
            # Log metric
            await db.railway_db.execute(
                """INSERT INTO metrics (type, name, value, unit, user_id, file_id, metadata, created_at) 
                   VALUES ($1, $2, $3, $4, $5, $6, $7, NOW())""",
                'file_upload', 'file_size_bytes', file_size, 'bytes', user_id, db_record_id,
                {'filename': original_filename}
            )
            
            return db_record_id
        except Exception as e:
            logger.error(f"❌ [DB] Error recording metadata: {e}")
            raise

    async def find_file_record(self, file_id: str):
        """Find file record by ID across multiple tables"""
        try:
            if not db.railway_db:
                return None
                
            # Look up in file_uploads table
            record = await db.railway_db.fetchrow(
                "SELECT gemini_file_name, original_filename FROM file_uploads WHERE id = $1",
                file_id
            )
            if record:
                return {
                    'gemini_file_name': record['gemini_file_name'],
                    'original_filename': record['original_filename'],
                    'table_name': 'file_uploads'
                }
            
            # Look up in scraped_websites table
            record = await db.railway_db.fetchrow(
                "SELECT gemini_file_name, original_url FROM scraped_websites WHERE id = $1",
                file_id
            )
            if record:
                return {
                    'gemini_file_name': record['gemini_file_name'],
                    'original_filename': record.get('original_url', 'Unknown'),
                    'table_name': 'scraped_websites'
                }
            
            return None
        except Exception as e:
            logger.error(f"Error finding file record: {e}")
            return None

    async def delete_file_record(self, file_id: str, table_name: str):
        """Delete file record from specified table"""
        try:
            if db.railway_db:
                await db.railway_db.execute(f"DELETE FROM {table_name} WHERE id = $1", file_id)
        except Exception as e:
            logger.error(f"Error deleting file record: {e}")
            raise

    async def process_file_upload(self, file_data: dict, user_email: str) -> dict:
        """Process single file upload with business logic"""
        try:
            # Check for duplicate file
            duplicate = await self.check_duplicate_file(file_data['sha256'], user_email)
            if duplicate:
                return {"success": False, "message": "Duplicate file", "file_id": duplicate['id']}
            
            return {"success": True, "message": "File processed successfully"}
        except Exception as e:
            logger.error(f"Error processing file upload: {e}")
            raise

    async def handle_duplicate_check(self, sha256_hash: str, original_filename: str, replace_existing: bool = False) -> dict:
        """Handle duplicate file checking logic"""
        try:
            existing_file = await self.check_duplicate_file(sha256_hash, original_filename)
            if existing_file:
                match_type = existing_file.get("match_type", "unknown")
                if match_type == "hash":
                    return {"allow": True, "reason": "exact_duplicate"}
                else:
                    if not replace_existing:
                        return {"allow": False, "reason": "file_exists", "detail": f"File {original_filename} already exists. Set replace_existing=true."}
                    else:
                        # Delete existing file
                        await self.delete_existing_file_record(existing_file['id'])
                        return {"allow": True, "reason": "replaced"}
            return {"allow": True, "reason": "new_file"}
        except Exception as e:
            logger.error(f"Error checking duplicate file: {e}")
            return {"allow": False, "reason": "error"}

# Singleton instance
