"""
Scraping DAO for Celery Website Crawling Worker
Handles database operations for website management
"""
from typing import Dict, List, Any, Optional
import json
from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("scraping_dao", "celery-web-worker")

class ScrapingDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_website_by_id(self, website_id: int) -> Optional[Dict[str, Any]]:
        """Get website record by ID."""
        query = "SELECT * FROM scraped_websites WHERE id = :website_id"
        params = {"website_id": website_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = (await session.execute(text(query), params)).fetchone()
                logger.log_db_query(query, params, result)
                return dict(result._mapping) if result else None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def update_website_status(self, website_id: int, status: str, error_message: str = None):
        """Update website processing status."""
        logger.info(f"💾 [WEB_UPDATE_START] Updating website status")
        logger.info(f"   Website ID: {website_id}")
        logger.info(f"   New Status: {status}")
        logger.info(f"   Error Message: {error_message}")

        query = """
            UPDATE scraped_websites
            SET processing_status = :status, error_message = :error_message, updated_at = NOW()
            WHERE id = :website_id
        """
        params = {"status": status, "error_message": error_message, "website_id": website_id}

        logger.info(f"📝 [WEB_UPDATE_SQL] SQL Query:")
        logger.info(f"    {query}")
        logger.info(f"📊 [WEB_UPDATE_PARAMS] Parameters:")
        logger.info(f"    :status: {params['status']}")
        logger.info(f"    :error_message: {params['error_message']}")
        logger.info(f"    :website_id: {params['website_id']}")

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, "UPDATE 1")

                logger.info(f"✅ [WEB_UPDATE_SUCCESS] Website status updated")
                logger.info(f"   New Status: {status}")
                return result

        except Exception as e:
            logger.error(f"❌ [WEB_UPDATE_ERROR] Failed to update website status: {e}")
            logger.log_db_query(query, params, error=e)
            raise

    async def get_all_websites(self) -> List[Dict[str, Any]]:
        """Get all website records."""
        query = "SELECT * FROM scraped_websites ORDER BY created_at DESC"
        try:
            logger.log_db_operation(query, {})
            async with get_db_session() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
                logger.log_db_query(query, {}, rows)
                return [dict(row._mapping) for row in rows] if rows else []
        except Exception as e:
            logger.log_db_query(query, {}, error=e)
            return []

    async def record_scraped_metadata(self, record_data: Dict[str, Any]) -> Optional[int]:
        """
        Record scraped website metadata.
        Stores scraping_config in metadata JSONB for UI tree detection.
        """
        import json
        from urllib.parse import urlparse

        # Determine source type: use provided url_type or detect from URL
        # Priority: sitemap > domain only > specific page
        url_type = record_data.get('url_type')
        if not url_type:
            url = record_data.get('original_url', '')
            parsed_url = urlparse(url)
            path = parsed_url.path.strip('/')
            url_lower = url.lower()
            
            # Check for sitemap first (multiple patterns)
            is_sitemap = (
                url_lower.endswith('sitemap.xml') or
                url_lower.endswith('sitemap.xml.gz') or
                url_lower.endswith('sitemap_index.xml') or
                '/sitemap' in url_lower and (url_lower.endswith('.xml') or url_lower.endswith('.xml.gz')) or
                'sitemap' in path.lower() and path.lower().endswith('.xml')
            )
            
            if is_sitemap:
                url_type = "sitemap"
            elif not path:
                # Domain only (https://www.globistaan.com or https://www.globistaan.com/) → "website"
                url_type = "website"
            else:
                # With path (https://www.globistaan.com/index.html or /about) → "single"
                url_type = "single"

        logger.info(f"🌐 [WEB_INSERT_START] Recording scraped website metadata")
        logger.info(f"   URL: {record_data.get('original_url')}")
        logger.info(f"   Type: {url_type}")
        logger.info(f"   User Role ID: {record_data.get('user_role_id')}")

        # Prepare metadata with scraping_config for UI tree detection
        metadata = {
            "scraping_config": {
                "source": url_type,  # 'sitemap', 'website', 'single'
            }
        }

        query = """
            INSERT INTO scraped_websites (
                user_role_id, original_url, processing_status, metadata,
                created_at, updated_at
            ) VALUES (
                :user_role_id, :original_url, :processing_status, :metadata::jsonb,
                NOW(), NOW()
            ) RETURNING id
        """
        params = {
            "user_role_id": record_data.get('user_role_id'),
            "original_url": record_data.get('original_url'),
            "processing_status": record_data.get('processing_status', 'pending'),
            "metadata": json.dumps(metadata)
        }

        logger.info(f"📝 [WEB_INSERT_QUERY] SQL Query:")
        logger.info(f"    {query}")
        logger.info(f"📊 [WEB_INSERT_PARAMS] Parameters:")
        logger.info(f"    :user_role_id: {params['user_role_id']}")
        logger.info(f"    :original_url: {params['original_url']}")
        logger.info(f"    :processing_status: {params['processing_status']}")
        logger.info(f"    :metadata: {params['metadata']}")

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = (await session.execute(text(query), params)).scalar()
                logger.info(f"✅ [WEB_INSERT_SUCCESS] Website record created with ID: {result}")
                logger.log_db_query(query, params, result)
                await session.commit()
                return int(result) if result else None
        except Exception as e:
            logger.error(f"❌ [WEB_INSERT_ERROR] Failed to record website metadata: {e}")
            logger.error(f"   Query: {query}")
            logger.error(f"   Params: {params}")
            logger.log_db_query(query, params, error=e)
            return None

    async def delete_website_record(self, url: str):
        """Delete website record from database."""
        logger.info(f"🗑️  [WEB_DELETE_START] Deleting website record")
        logger.info(f"   URL: {url}")

        query = "DELETE FROM scraped_websites WHERE original_url = :url"
        params = {"url": url}

        logger.info(f"📝 [WEB_DELETE_QUERY] SQL Query:")
        logger.info(f"    {query}")
        logger.info(f"📊 [WEB_DELETE_PARAMS] Parameters:")
        logger.info(f"    :url: {url}")

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                logger.info(f"✅ [WEB_DELETE_SUCCESS] Website record deleted. Result: {result}")
                logger.log_db_query(query, params, "DELETE 1")
                return result
        except Exception as e:
            logger.error(f"❌ [WEB_DELETE_ERROR] Failed to delete website record: {e}")
            logger.error(f"   Query: {query}")
            logger.error(f"   URL: {url}")
            logger.log_db_query(query, params, error=e)
            raise

    async def check_duplicate_website(self, original_url: str) -> Optional[Dict[str, Any]]:
        """
        Check if a website with the same URL already exists (excluding deleted records).

        Helps prevent duplicate scraping when dealing with soft-deleted records.
        """
        logger.info(f"🔍 [WEB_DUPLICATE_CHECK] Checking for duplicate website URL: {original_url}")

        query = """
            SELECT id, original_url, processing_status, created_at
            FROM scraped_websites
            WHERE original_url = :url AND processing_status != 'deleted'
        """
        params = {"url": original_url}

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = (await session.execute(text(query), params)).fetchone()

                if result:
                    logger.info(f"⚠️  [WEB_DUPLICATE_FOUND] Website already exists (ID: {result.id}, Status: {result.processing_status})")
                    logger.log_db_query(query, params, result)
                    return {
                        "id": result.id,
                        "original_url": result.original_url,
                        "processing_status": result.processing_status,
                        "created_at": result.created_at
                    }
                else:
                    logger.info(f"✅ [WEB_DUPLICATE_NOT_FOUND] No active website found for URL: {original_url}")
                    logger.log_db_query(query, params, result=None)
                    return None

        except Exception as e:
            logger.warning(f"⚠️  [WEB_DUPLICATE_CHECK_ERROR] Error checking for duplicate website: {e}")
            logger.log_db_query(query, params, error=e)
            return None

    async def get_admin_user_role_id(self, user_email: str = None) -> Optional[int]:
        """Get admin user role ID from database."""
        try:
            async with get_db_session() as session:
                # Get admin role first
                admin_role = (await session.execute(text("SELECT id FROM roles WHERE role_name = 'admin' LIMIT 1"))).scalar()

                if not admin_role:
                    logger.warning("⚠️ Admin role not found in database")
                    return None

                # Get user role mapping for the admin email (join with users table)
                email_to_search = user_email or 'globistaan@gmail.com'
                user_role = (await session.execute(text("""SELECT urm.user_role_id
                       FROM user_role_mapping urm
                       JOIN users u ON urm.user_id = u.id
                       WHERE u.email = :email AND urm.role_id = :role_id LIMIT 1"""),
                       {"email": email_to_search, "role_id": admin_role})).scalar()

                if not user_role:
                    logger.warning(f"⚠️ No admin user role found for {email_to_search}")

                return user_role
        except Exception as e:
            logger.warning(f"⚠️ Error getting admin user role: {e}")
            return None

    async def record_child_page(
        self,
        parent_id: int,
        page_url: str,
        gemini_file_name: str = None,
        gemini_file_uri: str = None,
        file_search_metadata: Dict[str, Any] = None,
        user_role_id: int = None,
        file_size: int = 0,
        char_count: int = 0,
        title: str = None,
        description: str = None,
        crawl_session_id: str = None,
        processed_content_s3_key: str = None
    ) -> Optional[int]:
        """
        Record a child page immediately after it's uploaded to Gemini.
        This creates a new record in scraped_websites with parent_id set to the website.

        Returns: page record id or None on failure
        """
        import json

        logger.info(f"📄 [CHILD_PAGE_INSERT] Recording child page for parent {parent_id}")
        logger.info(f"   URL: {page_url}")
        logger.info(f"   Gemini File: {gemini_file_name}")
        logger.info(f"   Title: {title}")

        # Determine child page type based on URL
        url_lower = page_url.lower()
        is_sitemap = (
            url_lower.endswith('sitemap.xml') or
            url_lower.endswith('sitemap.xml.gz') or
            url_lower.endswith('sitemap_index.xml') or
            '/sitemap' in url_lower and url_lower.endswith('.xml')
        )
        
        # Child pages are either sitemaps or webpages (never "website")
        child_source_type = "sitemap" if is_sitemap else "single"
        
        logger.info(f"   Child Type: {child_source_type}")
        
        # Prepare metadata with scraping_config for proper UI classification
        child_metadata = file_search_metadata or {}
        if 'scraping_config' not in child_metadata:
            child_metadata['scraping_config'] = {}
        child_metadata['scraping_config']['source'] = child_source_type

        query = """
            INSERT INTO scraped_websites (
                parent_id, original_url, processing_status,
                gemini_file_name, gemini_file_uri, metadata, depth, user_role_id,
                file_size, char_count, title, description, crawl_session_id,
                pages_scraped, processed_content_s3_key,
                created_at, updated_at
            ) VALUES (
                :parent_id, :page_url, :processing_status,
                :gemini_file_name, :gemini_file_uri, :metadata::jsonb, :depth, :user_role_id,
                :file_size, :char_count, :title, :description, :crawl_session_id,
                :pages_scraped, :processed_content_s3_key,
                NOW(), NOW()
            ) RETURNING id
        """

        params = {
            "parent_id": parent_id,
            "page_url": page_url,
            "processing_status": 'completed' if gemini_file_name else 'processing',
            "gemini_file_name": gemini_file_name,
            "gemini_file_uri": gemini_file_uri,
            "metadata": json.dumps(child_metadata),
            "depth": 1,
            "user_role_id": user_role_id,
            "file_size": file_size,
            "char_count": char_count,
            "title": title,
            "description": description,
            "crawl_session_id": crawl_session_id,
            "pages_scraped": 1,
            "processed_content_s3_key": processed_content_s3_key
        }

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                # First, check if parent exists
                parent_check_query = "SELECT id FROM scraped_websites WHERE id = :parent_id"
                parent_exists = (await session.execute(text(parent_check_query), {"parent_id": parent_id})).scalar()

                if not parent_exists:
                    logger.warning(f"⚠️  [CHILD_PAGE_SKIP] Parent ID {parent_id} not found, skipping child page")
                    logger.warning(f"   URL: {page_url}")
                    logger.warning(f"   Parent may have been deleted or failed to create")
                    return None

                # Parent exists, proceed with insert
                result = (await session.execute(text(query), params)).scalar()
                await session.commit()
                logger.info(f"✅ [CHILD_PAGE_SUCCESS] Recorded child page with ID: {result}")
                logger.log_db_query(query, params, result)
                return int(result) if result else None
        except Exception as e:
            # Check if it's a foreign key constraint error
            if "foreign key constraint" in str(e) and "parent_id" in str(e):
                logger.warning(f"⚠️  [CHILD_PAGE_SKIP] Parent was deleted during processing")
                logger.warning(f"   URL: {page_url}")
                logger.warning(f"   Parent ID: {parent_id}")
                logger.warning(f"   This can happen if parent was deleted while children were being scraped")
                return None

            logger.error(f"❌ [CHILD_PAGE_ERROR] Failed to record child page: {e}")
            logger.error(f"   URL: {page_url}")
            logger.error(f"   Parent ID: {parent_id}")
            logger.log_db_query(query, params, error=e)
            return None

    async def finalize_website_metadata(
        self,
        website_id: int,
        page_count: int,
        total_size_bytes: int,
        total_char_count: int,
        file_search_metadata: Dict[str, Any]
    ) -> bool:
        """
        Update parent website record with aggregate stats after scraping completes.
        Called once per job after all pages are processed.

        Returns: True on success, False on failure
        """
        import json

        logger.info(f"💾 [FINALIZE_START] Updating website record {website_id}")
        logger.info(f"   Pages: {page_count}")
        logger.info(f"   Size: {total_size_bytes:,} bytes")
        logger.info(f"   Chars: {total_char_count:,}")

        query = """
            UPDATE scraped_websites
            SET pages_scraped = :page_count,
                metadata = :metadata,
                file_size = :file_size,
                char_count = :char_count,
                processing_status = 'completed',
                updated_at = NOW()
            WHERE id = :website_id
        """

        params = {
            "page_count": page_count,
            "metadata": json.dumps(file_search_metadata),
            "file_size": total_size_bytes,
            "char_count": total_char_count,
            "website_id": website_id
        }

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                await session.execute(text(query), params)
                await session.commit()
                logger.info(f"✅ [FINALIZE_SUCCESS] Website record updated")
                logger.log_db_query(query, params, "UPDATE succeeded")
                return True
        except Exception as e:
            logger.error(f"❌ [FINALIZE_ERROR] Failed to finalize website record: {e}")
            logger.error(f"   Website ID: {website_id}")
            logger.log_db_query(query, params, error=e)
            return False

    async def update_website_with_page_data(
        self,
        website_id: int,
        gemini_file_name: str,
        gemini_file_uri: str,
        file_size: int,
        char_count: int,
        title: str,
        description: str,
        crawl_session_id: str,
        file_search_metadata: Dict[str, Any],
        mark_completed: bool = True,
        processed_content_s3_key: str = None
    ) -> bool:
        """
        Update parent website record with single page data.
        
        Args:
            mark_completed: If True, marks status as 'completed'. 
                          If False, keeps current status (for multi-page crawls where parent should stay 'processing')

        Returns: True on success, False on failure
        """
        import json

        logger.info(f"💾 [UPDATE_WEBSITE_PAGE] Updating website {website_id} with page data")
        logger.info(f"   Title: {title}")
        logger.info(f"   File Size: {file_size:,} bytes")
        logger.info(f"   Char Count: {char_count:,}")
        logger.info(f"   Mark as completed: {mark_completed}")

        # First, get the existing metadata to preserve scraping_config
        get_query = "SELECT metadata FROM scraped_websites WHERE id = :website_id"
        existing_metadata = {}

        try:
            async with get_db_session() as session:
                result = (await session.execute(text(get_query), {"website_id": website_id})).scalar()
                if result:
                    if isinstance(result, dict):
                        existing_metadata = result
                    elif isinstance(result, str):
                        try:
                            existing_metadata = json.loads(result)
                        except (json.JSONDecodeError, ValueError):
                            existing_metadata = {}
        except Exception as e:
            logger.warning(f"⚠️ Could not fetch existing metadata: {e}")

        # Merge existing metadata with file_search_metadata
        # Preserve scraping_config from existing metadata
        merged_metadata = {**existing_metadata, **file_search_metadata}

        logger.info(f"   Merged metadata: {merged_metadata}")

        # Build query based on mark_completed flag
        if mark_completed:
            query = """
                UPDATE scraped_websites
                SET gemini_file_name = :gemini_file_name,
                    gemini_file_uri = :gemini_file_uri,
                    file_size = :file_size,
                    char_count = :char_count,
                    title = :title,
                    description = :description,
                    crawl_session_id = :crawl_session_id,
                    pages_scraped = :pages_scraped,
                    metadata = :metadata::jsonb,
                    processed_content_s3_key = :processed_content_s3_key,
                    processing_status = 'completed',
                    updated_at = NOW()
                WHERE id = :website_id
            """
        else:
            # Don't update processing_status - keep it as 'processing' for multi-page crawls
            query = """
                UPDATE scraped_websites
                SET gemini_file_name = :gemini_file_name,
                    gemini_file_uri = :gemini_file_uri,
                    file_size = :file_size,
                    char_count = :char_count,
                    title = :title,
                    description = :description,
                    crawl_session_id = :crawl_session_id,
                    pages_scraped = :pages_scraped,
                    metadata = :metadata::jsonb,
                    processed_content_s3_key = :processed_content_s3_key,
                    updated_at = NOW()
                WHERE id = :website_id
            """

        params = {
            "gemini_file_name": gemini_file_name,
            "gemini_file_uri": gemini_file_uri,
            "file_size": file_size,
            "char_count": char_count,
            "title": title,
            "description": description,
            "crawl_session_id": crawl_session_id,
            "pages_scraped": 1,
            "metadata": json.dumps(merged_metadata),
            "processed_content_s3_key": processed_content_s3_key,
            "website_id": website_id
        }

        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                await session.execute(text(query), params)
                await session.commit()
                if mark_completed:
                    logger.info(f"✅ [UPDATE_WEBSITE_PAGE_SUCCESS] Website record updated and marked as completed")
                else:
                    logger.info(f"✅ [UPDATE_WEBSITE_PAGE_SUCCESS] Website record updated (status unchanged)")
                logger.log_db_query(query, params, "UPDATE succeeded")
                return True
        except Exception as e:
            logger.error(f"❌ [UPDATE_WEBSITE_PAGE_ERROR] Failed to update website: {e}")
            logger.error(f"   Website ID: {website_id}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            logger.log_db_query(query, params, error=e)
            return False

    async def check_and_update_parent_completion(self, parent_id: int) -> bool:
        """
        Check if all child pages of a parent website/sitemap are completed.
        If all children are completed, update parent status to 'completed'.

        This is called after each child page is recorded to ensure parent
        status is updated as soon as all children finish processing.

        Returns: True if parent was updated to completed, False otherwise
        """
        logger.info(f"🔍 [PARENT_CHECK] Checking completion status for parent {parent_id}")

        try:
            async with get_db_session() as session:
                # Get parent record
                parent = (await session.execute(text("SELECT id, processing_status FROM scraped_websites WHERE id = :parent_id"),
                    {"parent_id": parent_id})).fetchone()

                if not parent:
                    logger.warning(f"⚠️ [PARENT_CHECK] Parent {parent_id} not found")
                    return False

                # Skip if parent is already completed or failed
                if parent.processing_status in ('completed', 'failed', 'cancelled', 'deleted'):
                    logger.info(f"ℹ️ [PARENT_CHECK] Parent {parent_id} already in terminal state: {parent.processing_status}")
                    return False

                # Count total children and completed children
                stats = (await session.execute(text("""
                    SELECT
                        COUNT(*) as total_children,
                        COUNT(*) FILTER (WHERE processing_status = 'completed') as completed_children,
                        COUNT(*) FILTER (WHERE processing_status IN ('failed', 'cancelled')) as failed_children
                    FROM scraped_websites
                    WHERE parent_id = :parent_id
                """), {"parent_id": parent_id})).fetchone()

                total = stats.total_children
                completed = stats.completed_children
                failed = stats.failed_children

                logger.info(f"📊 [PARENT_CHECK] Parent {parent_id} children status:")
                logger.info(f"   Total: {total}")
                logger.info(f"   Completed: {completed}")
                logger.info(f"   Failed: {failed}")
                logger.info(f"   In Progress: {total - completed - failed}")

                # If no children yet, parent is still being processed
                if total == 0:
                    logger.info(f"ℹ️ [PARENT_CHECK] Parent {parent_id} has no children yet")
                    return False

                # If all children are completed, mark parent as completed
                if completed == total:
                    logger.info(f"✅ [PARENT_COMPLETE] All {total} children completed for parent {parent_id}")

                    # Update parent status to completed
                    await session.execute(text("""
                        UPDATE scraped_websites
                        SET processing_status = 'completed',
                            updated_at = NOW()
                        WHERE id = :parent_id
                    """), {"parent_id": parent_id})
                    await session.commit()

                    logger.info(f"✅ [PARENT_UPDATE] Parent {parent_id} marked as completed")
                    return True

                # If all children are in terminal state (completed or failed), mark parent as completed
                elif completed + failed == total:
                    logger.info(f"⚠️ [PARENT_PARTIAL] Parent {parent_id}: {completed} completed, {failed} failed out of {total}")

                    # Update parent status to completed (even with some failures)
                    await session.execute(text("""
                        UPDATE scraped_websites
                        SET processing_status = 'completed',
                            updated_at = NOW()
                        WHERE id = :parent_id
                    """), {"parent_id": parent_id})
                    await session.commit()

                    logger.info(f"✅ [PARENT_UPDATE] Parent {parent_id} marked as completed (with {failed} failures)")
                    return True

                else:
                    logger.info(f"⏳ [PARENT_PENDING] Parent {parent_id} still has children in progress")
                    return False

        except Exception as e:
            logger.error(f"❌ [PARENT_CHECK_ERROR] Failed to check parent completion: {e}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            return False
