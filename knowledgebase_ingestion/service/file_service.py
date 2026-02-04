"""
File Service Layer for Knowledgebase Ingestion
Provides business logic for file operations
"""
from typing import Any, Dict, Optional

from knowledgebase_ingestion.core import db
from knowledgebase_ingestion.core.otel_logger import get_otel_logger

logger = get_otel_logger("file_service", "knowledgebase-ingestion")

class FileService:
    """Service layer for file operations"""
    
    def __init__(self):
        pass  # No DAO needed - using direct database calls

    async def check_duplicate_file(self, sha256_hash: str, original_filename: str) -> Optional[Dict[str, Any]]:
        """Check if a file with the same hash or name already exists."""
        try:
            from knowledgebase_ingestion.core.db import get_db_connection
            
            async with get_db_connection() as conn:
                # Check by hash first (exact duplicate)
                existing = await conn.fetchrow(
                    "SELECT id, original_filename, display_name, sha256_hash, file_size, gemini_file_name, version FROM file_uploads WHERE sha256_hash = $1",
                    sha256_hash
                )
                if existing:
                    return {
                        "id": str(existing['id']),
                        "original_filename": existing['original_filename'],
                        "display_name": existing['display_name'],
                        "sha256_hash": existing['sha256_hash'],
                        "file_size": existing['file_size'],
                        "gemini_file_name": existing['gemini_file_name'],
                        "version": existing.get('version', 1),
                        "match_type": "hash"
                    }
                
                # Check by filename (same name, different content)
                existing_by_name = await conn.fetchrow(
                    "SELECT id, original_filename, display_name, sha256_hash, file_size, gemini_file_name, version FROM file_uploads WHERE original_filename = $1",
                    original_filename
                )
                if existing_by_name:
                    return {
                        "id": str(existing_by_name['id']),
                        "original_filename": existing_by_name['original_filename'],
                        "display_name": existing_by_name['display_name'],
                        "sha256_hash": existing_by_name['sha256_hash'],
                        "file_size": existing_by_name['file_size'],
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
            from knowledgebase_ingestion.core.db import get_db_connection
            
            async with get_db_connection() as conn:
                await conn.execute("DELETE FROM file_uploads WHERE id = $1", db_id)
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
            
            # Use the new DatabaseManager pattern
            from knowledgebase_ingestion.core.db import get_db_connection
            
            db_record_id = None
            try:
                async with get_db_connection() as conn:
                    db_record_id = await conn.fetchval(
                        """INSERT INTO file_uploads (user_role_id, original_filename, display_name, file_extension, 
                           gemini_file_name, gemini_file_uri, mime_type, file_size, sha256_hash, 
                           gemini_state, version, created_at) 
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, NOW()) RETURNING id""",
                        None, original_filename, file_display_name, file_ext.lstrip('.'),  # user_role_id = NULL for now
                        uploaded_file.name, getattr(uploaded_file, 'uri', None), mime_type,
                        file_size, sha256_hash, final_state, version
                    )
                    
                    # Log metric
                    await conn.execute(
                        """INSERT INTO metrics (metric_type, metric_name, value, unit, tags, created_at) 
                           VALUES ($1, $2, $3, $4, $5, NOW())""",
                        'file_upload', 'file_size_bytes', file_size, 'bytes', 
                        {'user_id': user_id, 'file_id': db_record_id, 'filename': original_filename}
                    )
            except Exception as db_error:
                logger.error(f"❌ [DB] Database error during metadata recording: {db_error}")
                return None
            
            logger.info(f"✅ [DB] Record created with ID: {db_record_id} (version {version})")
            return db_record_id
            
        except Exception as e:
            logger.error(f"❌ [DB] Error recording metadata: {e}")
            raise

    async def find_file_record(self, file_id: str):
        """Find file record by ID across multiple tables"""
        try:
            from knowledgebase_ingestion.core.db import get_db_connection
            
            async with get_db_connection() as conn:
                # Look up in file_uploads table
                record = await conn.fetchrow(
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
                record = await conn.fetchrow(
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
            from knowledgebase_ingestion.core.db import get_db_connection
            
            async with get_db_connection() as conn:
                await conn.execute(f"DELETE FROM {table_name} WHERE id = $1", file_id)
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

    async def get_all_files(self) -> list:
        """Get all uploaded files from the database."""
        try:
            from knowledgebase_ingestion.core.db import get_db_connection
            
            async with get_db_connection() as conn:
                files = await conn.fetch(
                    """SELECT id, original_filename, display_name, file_extension, mime_type, 
                       file_size, sha256_hash, gemini_state, created_at, version
                       FROM file_uploads 
                       ORDER BY created_at DESC"""
                )
                
                # Convert to list of dicts
                result = []
                for file in files:
                    result.append({
                        "id": str(file['id']),
                        "original_filename": file['original_filename'],
                        "display_name": file['display_name'],
                        "file_extension": file['file_extension'],
                        "mime_type": file['mime_type'],
                        "size_bytes": file['file_size'],  # Map file_size to size_bytes for API consistency
                        "sha256_hash": file['sha256_hash'],
                        "gemini_state": file['gemini_state'],
                        "processed_at": None,  # Not available in current schema
                        "created_at": file['created_at'].isoformat() if file['created_at'] else None,
                        "version": file.get('version', 1)
                    })
                
                logger.info(f"Retrieved {len(result)} files from database")
                return result
                
        except Exception as e:
            logger.error(f"Error getting all files: {e}")
            return []

    async def get_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get file record by ID"""
        try:
            from knowledgebase_ingestion.core.db import get_db_connection
            
            async with get_db_connection() as conn:
                file_record = await conn.fetchrow(
                    """SELECT id, original_filename, display_name, file_extension, mime_type, 
                       file_size, sha256_hash, gemini_state, created_at, version
                       FROM file_uploads 
                       WHERE id = $1""",
                    file_id
                )
                
                if not file_record:
                    return None
                    
                return {
                    "id": str(file_record['id']),
                    "original_filename": file_record['original_filename'],
                    "display_name": file_record['display_name'],
                    "file_extension": file_record['file_extension'],
                    "mime_type": file_record['mime_type'],
                    "size_bytes": file_record['file_size'],  # Map file_size to size_bytes for API consistency
                    "sha256_hash": file_record['sha256_hash'],
                    "gemini_state": file_record['gemini_state'],
                    "processed_at": None,  # Not available in current schema
                    "created_at": file_record['created_at'].isoformat() if file_record['created_at'] else None,
                    "version": file_record.get('version', 1)
                }
                
        except Exception as e:
            logger.error(f"Error getting file by ID: {e}")
            return None

    async def delete_file(self, file_id: str) -> bool:
        """Delete file by ID"""
        try:
            from knowledgebase_ingestion.core.db import get_db_connection
            
            async with get_db_connection() as conn:
                # First get the file record
                file_record = await self.get_file_by_id(file_id)
                if not file_record:
                    logger.warning(f"File not found: {file_id}")
                    return False
                
                # Delete from database
                await conn.execute("DELETE FROM file_uploads WHERE id = $1", file_id)
                
                logger.info(f"File deleted from database: {file_id}")
                return True
                
        except Exception as e:
            logger.error(f"Error deleting file: {e}")
            return False

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
