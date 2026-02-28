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

    def _normalize_error_message(self, error_message, metadata=None) -> str:
        """Normalize old generic error messages to include location info."""
        if not error_message:
            return error_message
        # Old generic message stored before per-location tracking was added
        if 'Website already exists' in error_message or 'Set replace_existing=true to update' in error_message:
            try:
                import json
                meta = metadata
                if isinstance(meta, str):
                    meta = json.loads(meta)
                in_filesearch = bool(meta and meta.get('file_search_metadata'))
            except Exception:
                in_filesearch = False
            location = "database and FileSearch" if in_filesearch else "database"
            return f"URL already existed in {location} when this task ran (duplicate detected)"
        return error_message

    async def check_duplicate_file(self, original_filename: str, sha256_hash: Optional[str] = None) -> Optional[Dict[str, Any]]:
        """Check if a file already exists by filename or hash (only active files)."""
        try:
            from shared.db import get_db_connection

            logger.info(f"🔍 [CHECK_DUPLICATE] Checking for duplicate: filename='{original_filename}', hash='{sha256_hash}'")
            logger.info(f"🔍 [CHECK_DUPLICATE] Hash is None: {sha256_hash is None}, Hash is empty: {not sha256_hash}")

            async with get_db_connection() as conn:
                logger.info(f"✅ [DB_CONNECTION] Got database connection")

                # Check by filename first - only consider actively processed files
                logger.info(f"🔍 [FILENAME_CHECK] Searching for filename match: {original_filename}")
                try:
                    existing_by_name = await conn.fetchrow(
                        "SELECT id, original_filename, display_name, sha256_hash, file_size, gemini_file_name, version FROM file_uploads WHERE original_filename = $1 AND processing_status IN ('pending', 'processing', 'queued', 'completed')",
                        original_filename
                    )
                    logger.info(f"🔍 [FILENAME_CHECK_RESULT] Query returned: {existing_by_name}")
                except Exception as e:
                    logger.error(f"❌ [FILENAME_CHECK_ERROR] Database error: {e}", exc_info=True)
                    raise
                if existing_by_name:
                    logger.info(f"✅ [FILENAME_MATCH] Found by filename: ID={existing_by_name['id']}")
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
                else:
                    logger.info(f"❌ [FILENAME_MATCH] No filename match found")

                # Check by hash if provided - detects same content with different filename
                if sha256_hash:
                    logger.info(f"🔍 [HASH_CHECK] Searching for hash match: {sha256_hash}")
                    try:
                        # Debug: Check all files with this exact hash (regardless of status)
                        logger.info(f"🔍 [HASH_CHECK] Running debug query for all files with this hash...")
                        all_with_hash = await conn.fetch(
                            "SELECT id, original_filename, sha256_hash, processing_status FROM file_uploads WHERE sha256_hash = $1 ORDER BY created_at DESC",
                            sha256_hash
                        )
                        logger.info(f"📊 [HASH_DEBUG] Files with this hash (ALL statuses): {len(all_with_hash)}")
                        for record in all_with_hash:
                            logger.info(f"   ID={record['id']}, filename={record['original_filename']}, status={record['processing_status']}")

                        # Now check only active files
                        logger.info(f"🔍 [HASH_CHECK] Running query for active files only...")
                        existing_by_hash = await conn.fetchrow(
                            "SELECT id, original_filename, display_name, sha256_hash, file_size, gemini_file_name, version FROM file_uploads WHERE sha256_hash = $1 AND processing_status IN ('pending', 'processing', 'queued', 'completed')",
                            sha256_hash
                        )
                        logger.info(f"📊 [HASH_CHECK_RESULT] Active file query returned: {existing_by_hash}")
                    except Exception as hash_err:
                        logger.error(f"❌ [HASH_CHECK_ERROR] Database error during hash check: {hash_err}", exc_info=True)
                        raise

                    if existing_by_hash:
                        logger.info(f"✅ [HASH_MATCH] Found by hash: ID={existing_by_hash['id']}, filename={existing_by_hash['original_filename']}")
                        return {
                            "id": str(existing_by_hash['id']),
                            "original_filename": existing_by_hash['original_filename'],
                            "display_name": existing_by_hash['display_name'],
                            "sha256_hash": existing_by_hash['sha256_hash'],
                            "file_size": existing_by_hash['file_size'],
                            "gemini_file_name": existing_by_hash['gemini_file_name'],
                            "version": existing_by_hash.get('version', 1),
                            "match_type": "hash"  # Same content, different filename
                        }
                    else:
                        logger.info(f"❌ [HASH_MATCH] No hash match found for hash: {sha256_hash}")
                else:
                    logger.info(f"⚠️  [HASH_CHECK] No hash provided - skipping hash check")

                logger.info(f"✅ [NO_DUPLICATE] No duplicate found")
                return None
        except Exception as e:
            logger.warning(f"Error checking for duplicate file: {e}")
            return None

    async def delete_existing_file_record(self, db_id: str) -> bool:
        """Delete an existing file record from both Gemini and database.

        Returns:
            bool: True if deletion succeeded, False otherwise
        """
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

                # Then mark as deleted in database (soft delete instead of hard delete)
                # This preserves audit trail and prevents orphaned references
                await conn.execute(
                    "UPDATE file_uploads SET processing_status = 'deleted', updated_at = NOW() WHERE id = $1",
                    numeric_id
                )
                logger.info(f"✅ Marked old file record as deleted in database: {db_id}")
                return True
        except Exception as e:
            logger.error(f"❌ Error deleting existing file record: {e}")
            return False

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

    async def get_all_files(self) -> list:
        """Get all uploaded files from the database."""
        try:
            from shared.db import get_db_connection

            async with get_db_connection() as conn:
                files = await conn.fetch(
                    """SELECT id, original_filename, display_name, file_extension, mime_type,
                       file_size, sha256_hash, gemini_state, created_at, version,
                       celery_task_id, processing_status, error_message
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
                        "source": "upload",  # Add source field for frontend
                        "celery_task_id": file['celery_task_id'],  # Task ID for async processing
                        "processing_status": file['processing_status'],  # Current task status
                        "error_message": self._normalize_error_message(file['error_message'])  # Failure reason if failed
                    })

                logger.info(f"Retrieved {len(result)} files from database")
                return result

        except Exception as e:
            logger.error(f"Error getting all files: {e}")
            return []

    async def get_all_websites_hierarchy(self) -> list:
        """
        Get all scraped websites grouped by crawl_session_id.
        Each session's websites are returned as separate hierarchical tree structures.
        """
        try:
            from shared.db import get_db_connection

            async with get_db_connection() as conn:
                # Get all websites with hierarchy info, ordered by session and depth
                websites = await conn.fetch(
                    """SELECT id, original_url, domain, title, description, pages_scraped,
                              file_size, parent_id, depth, crawl_session_id, created_at,
                              celery_task_id, processing_status, error_message, metadata
                       FROM scraped_websites
                       ORDER BY crawl_session_id DESC NULLS LAST, depth, created_at DESC"""
                )

                # Group websites by crawl_session_id
                sessions = {}
                for website in websites:
                    session_id = str(website['crawl_session_id']) if website['crawl_session_id'] else "unknown_session"
                    if session_id not in sessions:
                        sessions[session_id] = []
                    sessions[session_id].append(website)

                # Build hierarchical tree structure for each session
                all_root_nodes = []

                for session_id, session_websites in sessions.items():
                    # Create a map of all nodes in this session
                    nodes = {}
                    session_root_nodes = []

                    for website in session_websites:
                        # Detect if URL is a sitemap (multiple patterns)
                        url = website['original_url'].lower()
                        is_sitemap = (
                            url.endswith('sitemap.xml') or
                            url.endswith('sitemap.xml.gz') or
                            url.endswith('sitemap_index.xml') or
                            '/sitemap' in url and (url.endswith('.xml') or url.endswith('.xml.gz')) or
                            'sitemap' in url and url.endswith('.xml')
                        )
                        
                        # Extract source type from metadata.scraping_config
                        metadata = website['metadata']
                        source_type = None
                        if metadata and isinstance(metadata, dict):
                            scraping_config = metadata.get('scraping_config', {})
                            source_type = scraping_config.get('source')  # 'website', 'single', or 'sitemap'
                        
                        # Determine file_type based on source_type
                        if is_sitemap or source_type == "sitemap":
                            file_type = "SITEMAP"
                        elif source_type == "single":
                            file_type = "WEBPAGE"
                        else:
                            file_type = "WEBSITE"

                        node = {
                            "id": str(website['id']),
                            "original_filename": website['original_url'],  # Use URL as filename for consistency
                            "display_name": website['title'] or website['domain'] or website['original_url'],
                            "file_extension": "URL",
                            "mime_type": "text/html",
                            "file_type": file_type,
                            "size_bytes": website['file_size'] or 0,  # Markdown file size in bytes
                            "sha256_hash": None,
                            "gemini_state": "completed",
                            "processed_at": website['created_at'].isoformat() if website['created_at'] else None,
                            "created_at": website['created_at'].isoformat() if website['created_at'] else None,
                            "version": 1,
                            "source": "website",
                            "url": website['original_url'],
                            "domain": website['domain'],
                            "title": website['title'],
                            "description": website['description'],
                            "pages_scraped": website['pages_scraped'],
                            "file_size": website['file_size'] or 0,  # Raw markdown size
                            "depth": website['depth'],
                            "parent_id": website['parent_id'],
                            "crawl_session_id": session_id,
                            "children": [],  # Will be populated below
                            "is_expanded": False,  # Frontend can control this
                            "celery_task_id": website['celery_task_id'],  # Task ID for async processing
                            "processing_status": website['processing_status'],  # Current task status
                            "error_message": self._normalize_error_message(website['error_message'], website['metadata'])  # Failure reason if failed
                        }
                        nodes[website['id']] = node

                    # Build tree structure within this session
                    for website_id, node in nodes.items():
                        parent_id = node['parent_id']
                        if parent_id is None or parent_id not in nodes:
                            # This is a root node in this session
                            session_root_nodes.append(node)
                        else:
                            # This is a child node
                            parent_node = nodes[parent_id]
                            parent_node['children'].append(node)

                    all_root_nodes.extend(session_root_nodes)
                    logger.info(f"📊 Session {session_id[:8]}...: {len(session_websites)} websites, {len(session_root_nodes)} root nodes")

                logger.info(f"✅ Retrieved {len(websites)} websites across {len(sessions)} crawl sessions")
                return all_root_nodes

        except Exception as e:
            logger.error(f"Error getting websites hierarchy: {e}")
            return []

    async def get_all_knowledgebase(self) -> dict:
        """Get all knowledgebase items (files + websites) in unified structure."""
        try:
            files = await self.get_all_files()
            websites = await self.get_all_websites_hierarchy()

            # Helper function to count all nodes recursively
            def count_all_nodes(nodes):
                count = 0
                for node in nodes:
                    count += 1
                    if node.get('children'):
                        count += count_all_nodes(node['children'])
                return count

            total_website_pages = count_all_nodes(websites)
            root_website_count = len(websites)  # Root nodes only (each is a separate session)

            return {
                "files": files,  # Flat list of uploaded files
                "websites": websites,  # Hierarchical tree of scraped websites grouped by session
                "total_files": len(files),
                "total_websites": root_website_count,
                "summary": {
                    "uploaded_files": len(files),
                    "scraped_websites": root_website_count,  # Root websites (one per session)
                    "total_pages": total_website_pages  # All website pages including children
                }
            }
        except Exception as e:
            logger.error(f"Error getting knowledgebase: {e}")
            return {"files": [], "websites": [], "total_files": 0, "total_websites": 0, "summary": {}}

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

    async def delete_file_logic(self, file_id: str) -> Dict[str, Any]:
        """
        Delete a single file completely.

        Operations:
        1. Retrieves file record with all metadata and Celery task ID
        2. Revokes Celery worker tasks (kills running processors)
        3. Sets Redis task cancellation flags
        4. Deletes from Gemini (raw files and/or FileSearch store) and verifies deletion
        5. Marks record as deleted in database (soft delete for audit trail)

        Returns:
            {"success": bool, "message": str, ...details}
        """
        logger.info("=" * 80)
        logger.info(f"🗑️  [DELETE_FILE_LOGIC] Deleting file ID: {file_id}")
        logger.info("=" * 80)

        try:
            from shared.db import get_db_connection
            from knowledgebase_ingestion.core.ai import get_genai_client
            from shared.celery_dispatcher import file_celery
            from shared.redis_message_queue import RedisMessageQueue
            import json

            # Step 1: Get file record with celery_task_id
            logger.info(f"🔍 [LOOKUP] Fetching file record...")
            async with get_db_connection() as conn:
                file_record = await conn.fetchrow(
                    "SELECT id, original_filename, gemini_file_name, metadata, celery_task_id FROM file_uploads WHERE id = $1",
                    int(file_id)
                )

            if not file_record:
                logger.error(f"❌ File not found: {file_id}")
                return {
                    "success": False,
                    "message": "File not found",
                    "file_id": file_id
                }

            logger.info(f"✅ File found: {file_record['original_filename']}")
            logger.info(f"   Celery task ID: {file_record['celery_task_id']}")

            # Step 2: Revoke Celery task and set cancellation flag
            logger.info(f"🔪 [CELERY_REVOKE] Killing Celery worker task...")
            celery_task_revoked = False

            if file_record['celery_task_id']:
                try:
                    logger.info(f"   🔪 Revoking Celery task: {file_record['celery_task_id']}")
                    file_celery.control.revoke(file_record['celery_task_id'], terminate=True, signal='SIGKILL')
                    celery_task_revoked = True
                    logger.info(f"   ✅ Task revoked: {file_record['celery_task_id']}")
                except Exception as e:
                    logger.warning(f"   ⚠️  Could not revoke task {file_record['celery_task_id']}: {e}")

                # Set Redis cancellation flag for in-progress tasks
                logger.info(f"🚩 [REDIS_FLAG] Setting task cancellation flag...")
                try:
                    redis_queue = RedisMessageQueue()
                    redis_queue.set_task_cancelled(file_record['celery_task_id'])
                    logger.info(f"   ✅ Set cancellation flag for task: {file_record['celery_task_id']}")
                except Exception as e:
                    logger.warning(f"   ⚠️  Could not set cancellation flag: {e}")

            # Step 3: Delete from Gemini and verify
            logger.info(f"🤖 [GEMINI_DELETE] Deleting from Gemini and verifying...")
            deleted_from_gemini = False
            deleted_from_filesearch = False
            failed_deletes = 0

            try:
                genai_client = get_genai_client()
                if not genai_client:
                    logger.warning("⚠️  Gemini client not available (file will still be marked as deleted in DB)")
                else:
                    # Delete raw file if it exists
                    if file_record['gemini_file_name'] and not file_record['gemini_file_name'].startswith("documents/"):
                        try:
                            logger.info(f"   📍 Deleting raw Gemini file: {file_record['gemini_file_name']}")
                            genai_client.files.delete(name=file_record['gemini_file_name'])

                            # Verify deletion
                            try:
                                genai_client.files.get(name=file_record['gemini_file_name'])
                                logger.warning(f"   ⚠️  Verification FAILED: Raw file still exists: {file_record['gemini_file_name']}")
                                failed_deletes += 1
                            except:
                                # File not found = successfully deleted
                                deleted_from_gemini = True
                                logger.info(f"   ✅ Verified deleted from Gemini raw: {file_record['gemini_file_name']}")
                        except Exception as e:
                            logger.warning(f"   ⚠️  Could not delete from Gemini raw files: {e}")
                            failed_deletes += 1

                    # Delete from FileSearch store if metadata contains FileSearch info
                    metadata = file_record['metadata']
                    if metadata:
                        try:
                            if isinstance(metadata, str):
                                metadata = json.loads(metadata)

                            if metadata.get('type') == 'file_search':
                                store_name = metadata.get('file_search_store_name')
                                document_name = metadata.get('document_name')

                                if store_name and document_name:
                                    try:
                                        logger.info(f"   📍 Deleting FileSearch document: {document_name} from store: {store_name}")
                                        # Use force=True to delete document with all its parts/chunks
                                        genai_client.file_search_stores.documents.delete(
                                            name=document_name,
                                            config={"force": True}
                                        )

                                        # Verify deletion: check if document still exists
                                        try:
                                            documents = genai_client.file_search_stores.list_documents(
                                                file_search_store_name=store_name
                                            )
                                            doc_exists = any(doc.name == document_name for doc in documents)
                                            if doc_exists:
                                                logger.warning(f"   ⚠️  Verification FAILED: Document still exists: {document_name}")
                                                failed_deletes += 1
                                            else:
                                                deleted_from_filesearch = True
                                                logger.info(f"   ✅ Verified deleted from FileSearch: {document_name}")
                                        except Exception as verify_err:
                                            # If verification fails with 404, document is deleted
                                            if "404" in str(verify_err) or "not found" in str(verify_err).lower():
                                                deleted_from_filesearch = True
                                                logger.info(f"   ✅ Document deleted (404 on verification): {document_name}")
                                            else:
                                                logger.warning(f"   ⚠️  Could not verify FileSearch deletion: {verify_err}")
                                                # Assume delete was successful if no error on delete itself
                                                deleted_from_filesearch = True
                                    except Exception as fs_err:
                                        # Check if it's a "not found" error (already deleted)
                                        if "404" in str(fs_err) or "not found" in str(fs_err).lower():
                                            deleted_from_filesearch = True
                                            logger.info(f"   ✅ Document already deleted: {document_name}")
                                        else:
                                            logger.warning(f"   ❌ Failed to delete from FileSearch store: {fs_err}")
                                            failed_deletes += 1
                        except Exception as e:
                            logger.warning(f"   ⚠️  Error processing metadata: {e}")
            except Exception as e:
                logger.warning(f"⚠️  Error during Gemini deletion: {e}")

            # Step 4: Mark as deleted in database (soft delete)
            logger.info(f"💾 [DB_UPDATE] Marking file as deleted in database...")
            try:
                async with get_db_connection() as conn:
                    await conn.execute(
                        "UPDATE file_uploads SET processing_status = 'deleted', updated_at = NOW() WHERE id = $1",
                        int(file_id)
                    )
                logger.info(f"✅ File marked as deleted in database (record retained for audit trail)")
            except Exception as e:
                logger.error(f"❌ Error marking file as deleted: {e}")
                raise

            logger.info("=" * 80)
            logger.info(f"✅ [DELETE_FILE_COMPLETE] File deletion completed")
            logger.info("=" * 80)
            logger.info(f"   File: {file_record['original_filename']}")
            logger.info(f"   Celery task revoked: {celery_task_revoked}")
            logger.info(f"   Deleted from Gemini raw: {deleted_from_gemini}")
            logger.info(f"   Deleted from FileSearch: {deleted_from_filesearch}")
            logger.info(f"   Failed deletes: {failed_deletes}")
            logger.info(f"   Marked as deleted in DB: Yes")

            return {
                "success": True,
                "message": "File deleted successfully",
                "file_id": file_id,
                "filename": file_record['original_filename'],
                "celery_task_revoked": celery_task_revoked,
                "deleted_from_gemini": deleted_from_gemini,
                "deleted_from_filesearch": deleted_from_filesearch,
                "failed_deletes": failed_deletes
            }

        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ [DELETE_FILE_ERROR] Error deleting file: {e}")
            logger.error("=" * 80)

            return {
                "success": False,
                "message": f"Error deleting file: {str(e)}",
                "file_id": file_id,
                "error": str(e)
            }

    async def delete_website_logic(self, website_id: str, revoke_celery_tasks: bool = False) -> Dict[str, Any]:
        """
        Delete a single website and all its child pages with ATOMIC transaction.

        Operations (in order):
        1. Retrieves website record and all child pages
        2. Force kills parent's Celery task (if parent row and task exists)
        3. (Optional) Revokes child Celery tasks - only for "delete all" operations
        4. Deletes all documents from Gemini FileSearch store
        5. Verifies deletion from Gemini FileSearch
        6. ONLY THEN marks website and all children as deleted in database (atomic transaction)
        
        If Gemini deletion fails, the database is NOT updated (rollback).

        Args:
            website_id: ID of website/page to delete
            revoke_celery_tasks: If True, revoke child Celery tasks (only for "delete all")

        Returns:
            {"success": bool, "message": str, ...details}
        """
        logger.info("=" * 80)
        logger.info(f"🗑️  [DELETE_WEBSITE_LOGIC] Deleting website ID: {website_id}")
        logger.info(f"   Revoke child Celery tasks: {revoke_celery_tasks}")
        logger.info("=" * 80)

        try:
            from shared.db import get_db_connection
            from knowledgebase_ingestion.core.ai import get_genai_client
            import json

            # Step 1: Get website record and all child pages
            logger.info(f"🔍 [LOOKUP] Fetching website and child pages...")
            async with get_db_connection() as conn:
                website_record = await conn.fetchrow(
                    "SELECT id, original_url, metadata, celery_task_id, parent_id FROM scraped_websites WHERE id = $1",
                    int(website_id)
                )

                if not website_record:
                    logger.error(f"❌ Website not found: {website_id}")
                    return {
                        "success": False,
                        "message": "Website not found",
                        "website_id": website_id
                    }

                # Get all child pages (only if this is a parent)
                child_pages = []
                if website_record['parent_id'] is None:
                    child_pages = await conn.fetch(
                        "SELECT id, original_url, metadata, celery_task_id FROM scraped_websites WHERE parent_id = $1",
                        int(website_id)
                    )

            is_child = website_record['parent_id'] is not None
            logger.info(f"✅ Website found: {website_record['original_url']}")
            logger.info(f"   Type: {'Child Page' if is_child else 'Parent Website'}")
            logger.info(f"   Child pages: {len(child_pages)}")

            # Step 2: ALWAYS force kill parent's Celery task if this is a parent row
            revoked_tasks = 0
            if not is_child and website_record['celery_task_id']:
                logger.info(f"🔪 [PARENT_TASK_KILL] Force killing parent's Celery task...")
                from shared.celery_dispatcher import web_celery
                from shared.redis_message_queue import RedisMessageQueue
                
                parent_task_id = website_record['celery_task_id']
                try:
                    logger.info(f"   🔪 Force killing parent task: {parent_task_id}")
                    web_celery.control.revoke(parent_task_id, terminate=True, signal='SIGKILL')
                    revoked_tasks += 1
                    logger.info(f"   ✅ Parent task killed: {parent_task_id}")
                except Exception as e:
                    logger.warning(f"   ⚠️  Could not kill parent task {parent_task_id}: {e}")

                # Set Redis cancellation flag for parent task
                logger.info(f"🚩 [PARENT_FLAG] Setting cancellation flag for parent task...")
                try:
                    redis_queue = RedisMessageQueue()
                    redis_queue.set_task_cancelled(parent_task_id)
                    logger.info(f"   ✅ Set cancellation flag for parent task: {parent_task_id}")
                except Exception as e:
                    logger.warning(f"   ⚠️  Could not set cancellation flag for parent: {e}")

            # Step 3: Optionally revoke child Celery tasks (only for "delete all")
            if revoke_celery_tasks and child_pages:
                logger.info(f"🔪 [CHILD_TASKS_REVOKE] Revoking child Celery worker tasks...")
                from shared.celery_dispatcher import web_celery
                from shared.redis_message_queue import RedisMessageQueue
                
                child_task_ids = []
                for child in child_pages:
                    if child['celery_task_id']:
                        child_task_ids.append(child['celery_task_id'])

                # Revoke all child Celery tasks
                for task_id in child_task_ids:
                    try:
                        logger.info(f"   🔪 Revoking child task: {task_id}")
                        web_celery.control.revoke(task_id, terminate=True, signal='SIGKILL')
                        revoked_tasks += 1
                        logger.info(f"   ✅ Child task revoked: {task_id}")
                    except Exception as e:
                        logger.warning(f"   ⚠️  Could not revoke child task {task_id}: {e}")

                # Set Redis cancellation flags for child tasks
                logger.info(f"🚩 [CHILD_FLAGS] Setting task cancellation flags for children...")
                try:
                    redis_queue = RedisMessageQueue()
                    for task_id in child_task_ids:
                        try:
                            redis_queue.set_task_cancelled(task_id)
                            logger.info(f"   ✅ Set cancellation flag for child task: {task_id}")
                        except Exception as e:
                            logger.warning(f"   ⚠️  Could not set cancellation flag for {task_id}: {e}")
                except Exception as e:
                    logger.warning(f"⚠️  Error setting Redis cancellation flags: {e}")
            elif not revoke_celery_tasks:
                logger.info(f"ℹ️  [CHILD_TASKS_SKIP] Skipping child task revocation (individual delete)")

            # Step 4: Delete from Gemini FileSearch and verify (BEFORE DB update)
            logger.info(f"🤖 [GEMINI_DELETE] Deleting from Gemini FileSearch and verifying...")
            deleted_documents = 0
            failed_deletes = []
            gemini_deletion_successful = True

            try:
                genai_client = get_genai_client()
                if not genai_client:
                    logger.warning("⚠️  Gemini client not available - skipping FileSearch deletion")
                    gemini_deletion_successful = False
                else:
                    all_pages = [website_record] + child_pages

                    for page in all_pages:
                        metadata = page['metadata']
                        if metadata:
                            try:
                                if isinstance(metadata, str):
                                    metadata = json.loads(metadata)

                                # Delete FileSearch document if metadata contains FileSearch info
                                if metadata.get('type') == 'file_search' or 'file_search_store_name' in metadata:
                                    store_name = metadata.get('file_search_store_name')
                                    document_name = metadata.get('document_name')

                                    if store_name and document_name:
                                        try:
                                            logger.info(f"   📍 Deleting: {document_name} from store: {store_name}")
                                            # Use force=True to delete document with all its parts/chunks
                                            genai_client.file_search_stores.documents.delete(
                                                name=document_name,
                                                config={"force": True}
                                            )

                                            # Verify deletion: check if document still exists
                                            try:
                                                documents = genai_client.file_search_stores.list_documents(
                                                    file_search_store_name=store_name
                                                )
                                                doc_exists = any(doc.name == document_name for doc in documents)
                                                if doc_exists:
                                                    error_msg = f"Document still exists after deletion: {document_name}"
                                                    logger.error(f"   ❌ VERIFICATION FAILED: {error_msg}")
                                                    failed_deletes.append({
                                                        "url": page['original_url'],
                                                        "document": document_name,
                                                        "error": error_msg
                                                    })
                                                    gemini_deletion_successful = False
                                                else:
                                                    deleted_documents += 1
                                                    logger.info(f"   ✅ Verified deleted from FileSearch: {page['original_url']}")
                                            except Exception as verify_err:
                                                # If verification fails but delete succeeded, consider it successful
                                                if "404" in str(verify_err) or "not found" in str(verify_err).lower():
                                                    deleted_documents += 1
                                                    logger.info(f"   ✅ Document deleted (404 on verification): {page['original_url']}")
                                                else:
                                                    error_msg = f"Could not verify deletion: {verify_err}"
                                                    logger.warning(f"   ⚠️  {error_msg}")
                                                    # Assume successful if delete didn't error
                                                    deleted_documents += 1
                                        except Exception as fs_err:
                                            # Check if it's a "not found" error (already deleted)
                                            if "404" in str(fs_err) or "not found" in str(fs_err).lower():
                                                deleted_documents += 1
                                                logger.info(f"   ✅ Document already deleted: {page['original_url']}")
                                            else:
                                                error_msg = f"Failed to delete from FileSearch: {fs_err}"
                                                logger.error(f"   ❌ {error_msg}")
                                                failed_deletes.append({
                                                    "url": page['original_url'],
                                                    "document": document_name,
                                                    "error": error_msg
                                                })
                                                gemini_deletion_successful = False
                            except Exception as e:
                                logger.warning(f"   ⚠️  Error processing metadata: {e}")
            except Exception as e:
                logger.error(f"❌ Error during Gemini deletion: {e}")
                gemini_deletion_successful = False

            # Step 4: ONLY mark as deleted in DB if Gemini deletion was successful
            if not gemini_deletion_successful:
                logger.error("=" * 80)
                logger.error(f"❌ [ATOMIC_ROLLBACK] Gemini deletion failed - NOT updating database")
                logger.error("=" * 80)
                logger.error(f"   Failed deletes: {len(failed_deletes)}")
                for fail in failed_deletes:
                    logger.error(f"   - {fail['url']}: {fail['error']}")
                
                return {
                    "success": False,
                    "message": "Gemini FileSearch deletion failed - database not updated (atomic rollback)",
                    "website_id": website_id,
                    "url": website_record['original_url'],
                    "failed_deletes": failed_deletes,
                    "documents_deleted_from_filesearch": deleted_documents
                }

            logger.info(f"💾 [DB_UPDATE] All Gemini deletions verified - marking as deleted in database...")
            try:
                async with get_db_connection() as conn:
                    async with conn.transaction():
                        # Mark the website/page as deleted
                        await conn.execute(
                            "UPDATE scraped_websites SET processing_status = 'deleted', updated_at = NOW() WHERE id = $1",
                            int(website_id)
                        )

                        # Mark all child pages as deleted (only if this is a parent)
                        if child_pages:
                            await conn.execute(
                                "UPDATE scraped_websites SET processing_status = 'deleted', updated_at = NOW() WHERE parent_id = $1",
                                int(website_id)
                            )

                logger.info(f"✅ {'Website and all child pages' if child_pages else 'Page'} marked as deleted")
                logger.info(f"   (Records retained in database for audit trail)")
            except Exception as e:
                logger.error(f"❌ Error marking as deleted in database: {e}")
                raise

            logger.info("=" * 80)
            logger.info(f"✅ [DELETE_COMPLETE] Atomic deletion completed successfully")
            logger.info("=" * 80)
            logger.info(f"   URL: {website_record['original_url']}")
            logger.info(f"   Type: {'Child Page' if is_child else 'Parent Website'}")
            logger.info(f"   Child pages deleted: {len(child_pages)}")
            logger.info(f"   Celery tasks revoked: {revoked_tasks}")
            logger.info(f"   Documents deleted from FileSearch: {deleted_documents}")
            logger.info(f"   Marked as deleted in DB: Yes")

            return {
                "success": True,
                "message": f"{'Website and all child pages' if child_pages else 'Page'} deleted successfully (atomic)",
                "website_id": website_id,
                "url": website_record['original_url'],
                "is_child": is_child,
                "child_pages_deleted": len(child_pages),
                "celery_tasks_revoked": revoked_tasks,
                "documents_deleted_from_filesearch": deleted_documents,
                "failed_filesearch_deletes": 0
            }

        except Exception as e:
            logger.error("=" * 80)
            logger.error(f"❌ [DELETE_ERROR] Error during deletion: {e}")
            logger.error("=" * 80)
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")

            return {
                "success": False,
                "message": f"Error deleting website: {str(e)}",
                "website_id": website_id,
                "error": str(e)
            }

    async def handle_duplicate_check(self, original_filename: str, replace_existing: bool = False, sha256_hash: Optional[str] = None) -> dict:
        """Handle duplicate file checking logic by filename or hash"""
        try:
            existing_file = await self.check_duplicate_file(original_filename, sha256_hash)
            if existing_file:
                match_type = existing_file.get("match_type", "unknown")

                # Create user-friendly message based on match type
                if match_type == "hash":
                    detail_msg = f"This file content already exists with a different name: '{existing_file['original_filename']}'"
                else:
                    detail_msg = f"File '{original_filename}' already exists"

                if not replace_existing:
                    logger.warning(f"⚠️ {detail_msg}. replace_existing=false, rejecting upload.")
                    return {
                        "allow": False,
                        "reason": "file_exists",
                        "match_type": match_type,
                        "existing_file_id": existing_file['id'],
                        "existing_file_name": existing_file['original_filename'],
                        "existing_file_hash": existing_file['sha256_hash'],
                        "detail": detail_msg
                    }
                else:
                    # Delete existing file from both Gemini and DB
                    logger.info(f"🔄 Replacing existing file {original_filename} (ID: {existing_file['id']}, match_type={match_type})")
                    deletion_success = await self.delete_existing_file_record(existing_file['id'])

                    if deletion_success:
                        logger.info(f"✅ Successfully deleted existing file {original_filename} from Gemini and DB")
                        return {"allow": True, "reason": "replaced", "match_type": match_type}
                    else:
                        logger.error(f"❌ Failed to delete existing file during replacement")
                        return {"allow": False, "reason": "replacement_failed", "detail": f"Could not delete existing file with ID {existing_file['id']}"}
            logger.info(f"✅ No duplicates found for {original_filename}, allowing new upload")
            return {"allow": True, "reason": "new_file"}
        except Exception as e:
            logger.error(f"❌ Error checking duplicate file: {e}")
            return {"allow": False, "reason": "error"}

# Singleton instance
_file_service = None

def get_file_service() -> FileService:
    """Get singleton FileService instance."""
    global _file_service
    if _file_service is None:
        _file_service = FileService()
    return _file_service
