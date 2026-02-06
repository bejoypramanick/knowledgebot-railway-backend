"""
File Service Layer for Knowledgebase Ingestion
Provides business logic for file operations
"""
from typing import Any, Dict, Optional

from shared.otel_logger import get_otel_logger

logger = get_otel_logger("file_service", "knowledgebase-ingestion")

class FileService:
    """Service layer for file operations"""
    
    def __init__(self):
        pass  # No DAO needed - using direct database calls

    async def check_duplicate_file(self, sha256_hash: str, original_filename: str) -> Optional[Dict[str, Any]]:
        """Check if a file with the same hash or name already exists."""
        try:
            from shared.db import get_db_connection
            
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
        """Delete an existing file record from both Gemini and database."""
        try:
            from shared.db import get_db_connection
            from knowledgebase_ingestion.core.ai import get_genai_client

            # Convert db_id to integer if it's a numeric string
            try:
                numeric_id = int(db_id)
            except ValueError:
                numeric_id = db_id

            async with get_db_connection() as conn:
                # First, get the gemini_file_name before deleting
                record = await conn.fetchrow(
                    "SELECT gemini_file_name, original_filename FROM file_uploads WHERE id = $1",
                    numeric_id
                )

                if record and record['gemini_file_name']:
                    # Delete from Gemini first
                    try:
                        genai_client = get_genai_client()
                        if genai_client:
                            genai_client.files.delete(name=record['gemini_file_name'])
                            logger.info(f"✅ Deleted from Gemini: {record['gemini_file_name']}")
                    except Exception as gemini_error:
                        logger.warning(f"⚠️ Could not delete from Gemini (may already be deleted): {gemini_error}")

                # Then delete from database
                await conn.execute("DELETE FROM file_uploads WHERE id = $1", numeric_id)
                logger.info(f"✅ Deleted old file record from database: {db_id}")
        except Exception as e:
            logger.error(f"❌ Error deleting existing file record: {e}")

    async def get_admin_user_role_id(self, user_email: str) -> Optional[int]:
        """Get user_role_id for admin role only - only admins can upload files

        Args:
            user_email: The user's email address (e.g., 'globistaan@gmail.com')

        Returns:
            user_role_id if the user has admin privileges, None otherwise
        """
        try:
            from shared.db import get_db_connection

            async with get_db_connection() as conn:
                # First, look up the user by email to get their user_id
                user = await conn.fetchrow(
                    "SELECT id, email FROM users WHERE email = $1",
                    user_email
                )

                if not user:
                    logger.error(f"User not found: {user_email}")
                    return None

                user_id = user['id']

                # Get the admin role ID
                admin_role = await conn.fetchrow(
                    "SELECT id FROM roles WHERE role_name = 'admin'"
                )

                if not admin_role:
                    logger.error("Admin role not found in roles table")
                    return None

                admin_role_id = admin_role['id']

                # Check if user has admin role mapping
                admin_mapping = await conn.fetchrow(
                    """SELECT user_role_id, user_id as mapped_user_id, is_active
                       FROM user_role_mapping
                       WHERE user_id = $1 AND role_id = $2 AND is_active = true""",
                    user_id, admin_role_id
                )

                logger.info(f"🔍 Admin check for user {user_email} (user_id={user_id}):")
                logger.info(f"  - Looking for role_id {admin_role_id}")
                logger.info(f"  - Found mapping: {admin_mapping}")

                if admin_mapping:
                    logger.info(f"✅ User {user_email} has admin privileges (user_role_id: {admin_mapping['user_role_id']})")
                    return admin_mapping['user_role_id']
                else:
                    logger.warning(f"❌ User {user_email} does not have admin role - file upload denied")
                    logger.warning(f"  - Available mappings for user {user_email}:")

                    # Debug: Show all mappings for this user
                    all_mappings = await conn.fetch(
                        "SELECT urm.user_id, urm.role_id, r.role_name, urm.is_active "
                        "FROM user_role_mapping urm "
                        "JOIN roles r ON urm.role_id = r.id "
                        "WHERE urm.user_id = $1",
                        user_id
                    )

                    for mapping in all_mappings:
                        logger.info(f"    - Mapping: user_id={mapping['user_id']}, role_id={mapping['role_id']}, role={mapping['role_name']}, active={mapping['is_active']}")

                    return None

        except Exception as e:
            logger.error(f"Error checking admin user role ID: {e}")
            return None

    async def record_metadata(self, user_email: str, original_filename: str, file_display_name: str,
                             file_ext: str, uploaded_file: Any,
                             file_size: int, sha256_hash: str,
                             final_state: str, gemini_processed_at: Any, mime_type: str, version: int = 1,
                             file_search_metadata: Dict[str, Any] = None):
        """Persist file metadata and metrics to the PostgreSQL database.

        Args:
            user_email: The user's email address
            original_filename: Original name of the uploaded file
            file_display_name: Display name for the file
            file_ext: File extension
            uploaded_file: The uploaded file object
            file_size: File size in bytes
            sha256_hash: SHA256 hash of the file
            final_state: Gemini processing state
            gemini_processed_at: Timestamp when Gemini processed the file
            mime_type: MIME type of the file
            version: File version number (default: 1)
            file_search_metadata: FileSearch store metadata for deletion (contains store_name, document_name)
        """
        try:
            logger.info(f"🗄️ [DB] Saving metadata for {original_filename} (version {version}) - Size: {file_size} bytes")

            # Use the new DatabaseManager pattern
            from shared.db import get_db_connection
            import json

            # Verify user has admin role and get the user_role_id
            user_role_id = await self.get_admin_user_role_id(user_email)

            if user_role_id is None:
                raise PermissionError(f"User {user_email} does not have admin privileges to upload files")

            db_record_id = None
            try:
                async with get_db_connection() as conn:
                    # Prepare metadata JSON
                    metadata = file_search_metadata or {}
                    metadata_json = json.dumps(metadata)

                    db_record_id = await conn.fetchval(
                        """INSERT INTO file_uploads (user_role_id, original_filename, display_name, file_extension,
                           gemini_file_name, gemini_file_uri, mime_type, file_size, sha256_hash,
                           gemini_state, version, metadata, created_at)
                           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12::jsonb, NOW()) RETURNING id""",
                        user_role_id, original_filename, file_display_name, file_ext.lstrip('.'),  # Use admin user_role_id
                        uploaded_file.name, getattr(uploaded_file, 'uri', None), mime_type,
                        file_size, sha256_hash, final_state, version, metadata_json
                    )
                    
                    logger.info(f"✅ [DB] Record created with ID: {db_record_id}, Size: {file_size} bytes")

                    # Log metric (non-critical - ignore errors)
                    try:
                        import json
                        await conn.execute(
                            """INSERT INTO metrics (metric_type, metric_name, value, unit, tags, created_at)
                               VALUES ($1, $2, $3, $4, $5::jsonb, NOW())
                               ON CONFLICT (metric_type, metric_name) DO NOTHING""",
                            'file_upload', 'file_size_bytes', file_size, 'bytes',
                            json.dumps({'user_email': user_email, 'file_id': db_record_id, 'filename': original_filename})
                        )
                    except Exception as metric_error:
                        logger.warning(f"⚠️ Failed to log metric (non-critical): {metric_error}")
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
            from shared.db import get_db_connection

            logger.info(f"🔍 Looking for file record with ID: {file_id}")

            # Convert file_id to integer if it's a numeric string
            try:
                numeric_id = int(file_id)
            except ValueError:
                # If not a number, use as-is (might be a Gemini file name)
                numeric_id = file_id

            async with get_db_connection() as conn:
                # Look up in file_uploads table
                record = await conn.fetchrow(
                    "SELECT gemini_file_name, original_filename, metadata FROM file_uploads WHERE id = $1",
                    numeric_id
                )
                if record:
                    logger.info(f"✅ Found file record in file_uploads: {record}")
                    return {
                        'gemini_file_name': record['gemini_file_name'],
                        'original_filename': record['original_filename'],
                        'table_name': 'file_uploads',
                        'metadata': record.get('metadata')
                    }

                # Look up in scraped_websites table
                record = await conn.fetchrow(
                    "SELECT gemini_file_name, original_url, metadata FROM scraped_websites WHERE id = $1",
                    numeric_id
                )
                if record:
                    logger.info(f"✅ Found file record in scraped_websites: {record}")
                    return {
                        'gemini_file_name': record['gemini_file_name'],
                        'original_filename': record.get('original_url', 'Unknown'),
                        'table_name': 'scraped_websites',
                        'metadata': record.get('metadata')
                    }

                logger.warning(f"❌ No file record found for ID: {file_id}")
                return None
        except Exception as e:
            logger.error(f"Error finding file record: {e}")
            return None

    async def delete_file_record(self, file_id: str, table_name: str):
        """Delete file record from specified table"""
        try:
            from shared.db import get_db_connection

            # Convert file_id to integer if it's a numeric string
            try:
                numeric_id = int(file_id)
            except ValueError:
                # If not a number, use as-is
                numeric_id = file_id

            async with get_db_connection() as conn:
                await conn.execute(f"DELETE FROM {table_name} WHERE id = $1", numeric_id)
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
            from shared.db import get_db_connection
            
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
                        "file_type": (file['file_extension'] or '').upper() or 'Unknown',  # Add file_type for frontend
                        "size_bytes": file['file_size'],  # Map file_size to size_bytes for API consistency
                        "sha256_hash": file['sha256_hash'],
                        "gemini_state": file['gemini_state'],
                        "processed_at": None,  # Not available in current schema
                        "created_at": file['created_at'].isoformat() if file['created_at'] else None,
                        "version": file.get('version', 1),
                        "source": "upload"  # Add source field for frontend
                    })
                
                logger.info(f"Retrieved {len(result)} files from database")
                return result
                
        except Exception as e:
            logger.error(f"Error getting all files: {e}")
            return []

    async def get_file_by_id(self, file_id: str) -> Optional[Dict[str, Any]]:
        """Get file record by ID"""
        try:
            from shared.db import get_db_connection
            
            async with get_db_connection() as conn:
                file_record = await conn.fetchrow(
                    """SELECT id, original_filename, display_name, file_extension, mime_type, 
                       file_size, sha256_hash, gemini_state, created_at, version
                       FROM file_uploads 
                       WHERE id = $1""",
                    int(file_id)  # Convert string to integer for database query
                )
                
                if not file_record:
                    return None
                    
                return {
                    "id": str(file_record['id']),
                    "original_filename": file_record['original_filename'],
                    "display_name": file_record['display_name'],
                    "file_extension": file_record['file_extension'],
                    "mime_type": file_record['mime_type'],
                    "file_type": (file_record['file_extension'] or '').upper() or 'Unknown',  # Add file_type for frontend
                    "size_bytes": file_record['file_size'],  # Map file_size to size_bytes for API consistency
                    "sha256_hash": file_record['sha256_hash'],
                    "gemini_state": file_record['gemini_state'],
                    "processed_at": None,  # Not available in current schema
                    "created_at": file_record['created_at'].isoformat() if file_record['created_at'] else None,
                    "version": file_record.get('version', 1),
                    "source": "upload"  # Add source field for frontend
                }
                
        except Exception as e:
            logger.error(f"Error getting file by ID: {e}")
            return None

    async def delete_file(self, file_id: str) -> bool:
        """Delete file by ID"""
        try:
            from shared.db import get_db_connection
            
            async with get_db_connection() as conn:
                # First get the file record
                file_record = await self.get_file_by_id(file_id)
                if not file_record:
                    logger.warning(f"File not found: {file_id}")
                    return False
                
                # Delete from database
                await conn.execute("DELETE FROM file_uploads WHERE id = $1", int(file_id))
                
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
                    logger.info(f"📋 Exact hash match found for {original_filename} (ID: {existing_file['id']})")
                    return {"allow": True, "reason": "exact_duplicate"}
                else:
                    if not replace_existing:
                        logger.warning(f"⚠️ File {original_filename} already exists. replace_existing=false, rejecting upload.")
                        return {"allow": False, "reason": "file_exists", "detail": f"File {original_filename} already exists. Set replace_existing=true."}
                    else:
                        # Delete existing file from both Gemini and DB
                        logger.info(f"🔄 Replacing existing file {original_filename} (ID: {existing_file['id']})")
                        try:
                            await self.delete_existing_file_record(existing_file['id'])
                            logger.info(f"✅ Successfully deleted existing file {original_filename} from Gemini and DB")
                            return {"allow": True, "reason": "replaced"}
                        except Exception as delete_error:
                            logger.error(f"❌ Failed to delete existing file during replacement: {delete_error}")
                            return {"allow": False, "reason": "replacement_failed", "detail": f"Could not delete existing file: {delete_error}"}
            logger.info(f"✅ No duplicates found for {original_filename}, allowing new upload")
            return {"allow": True, "reason": "new_file"}
        except Exception as e:
            logger.error(f"❌ Error checking duplicate file: {e}")
            return {"allow": False, "reason": "error"}

# Singleton instance
