"""
Scraping DAO for Celery Website Crawling Worker
Handles database operations for website management
"""
from typing import Dict, List, Any, Optional
import json
from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("scraping_dao", "celery-web-worker")

class ScrapingDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def get_website_by_id(self, website_id: int) -> Optional[Dict[str, Any]]:
        """Get website record by ID."""
        query = "SELECT * FROM scraped_websites WHERE id = $1::int"
        params = {"website_id": website_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, website_id)
                logger.log_db_query(query, params, result)
                return dict(result) if result else None
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
            SET processing_status = $1::text, error_message = $2::text, updated_at = NOW()
            WHERE id = $3::int
        """
        params = [status, error_message, website_id]

        logger.info(f"📝 [WEB_UPDATE_SQL] SQL Query:")
        logger.info(f"    {query}")
        logger.info(f"📊 [WEB_UPDATE_PARAMS] Parameters:")
        logger.info(f"    $1 (processing_status): {params[0]}")
        logger.info(f"    $2 (error_message): {params[1]}")
        logger.info(f"    $3 (id): {params[2]}")

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, status, error_message, website_id)
                logger.log_db_query(query, params, result)

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
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, {}, result)
                return [dict(row) for row in result] if result else []
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
        # Domain only (https://www.globistaan.com or https://www.globistaan.com/) → "website"
        # With path (https://www.globistaan.com/index.html or /about) → "single"
        url_type = record_data.get('url_type')
        if not url_type:
            parsed_url = urlparse(record_data.get('original_url', ''))
            path = parsed_url.path.strip('/')
            url_type = "website" if not path else "single"

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
                $1, $2, $3, $4::jsonb,
                NOW(), NOW()
            ) RETURNING id
        """
        params = [
            record_data.get('user_role_id'),
            record_data.get('original_url'),
            record_data.get('processing_status', 'pending'),
            json.dumps(metadata)
        ]

        logger.info(f"📝 [WEB_INSERT_QUERY] SQL Query:")
        logger.info(f"    {query}")
        logger.info(f"📊 [WEB_INSERT_PARAMS] Parameters:")
        logger.info(f"    $1 (user_role_id): {params[0]}")
        logger.info(f"    $2 (original_url): {params[1]}")
        logger.info(f"    $3 (processing_status): {params[2]}")
        logger.info(f"    $4 (metadata): {params[3]}")

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, *params)
                logger.info(f"✅ [WEB_INSERT_SUCCESS] Website record created with ID: {result}")
                logger.log_db_query(query, params, result)
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

        query = "DELETE FROM scraped_websites WHERE original_url = $1::text"
        params = {"url": url}

        logger.info(f"📝 [WEB_DELETE_QUERY] SQL Query:")
        logger.info(f"    {query}")
        logger.info(f"📊 [WEB_DELETE_PARAMS] Parameters:")
        logger.info(f"    $1 (original_url): {url}")

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, url)
                logger.info(f"✅ [WEB_DELETE_SUCCESS] Website record deleted. Result: {result}")
                logger.log_db_query(query, params, result)
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
            WHERE original_url = $1::text AND processing_status != 'deleted'
        """
        params = {"url": original_url}

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, original_url)

                if result:
                    logger.info(f"⚠️  [WEB_DUPLICATE_FOUND] Website already exists (ID: {result['id']}, Status: {result['processing_status']})")
                    logger.log_db_query(query, params, result)
                    return {
                        "id": result['id'],
                        "original_url": result['original_url'],
                        "processing_status": result['processing_status'],
                        "created_at": result['created_at']
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
            async with get_db_connection() as conn:
                # Get admin role first
                admin_role = await conn.fetchval(
                    "SELECT id FROM roles WHERE role_name = 'admin' LIMIT 1"
                )

                if not admin_role:
                    logger.warning("⚠️ Admin role not found in database")
                    return None

                # Get user role mapping for the admin email (join with users table)
                email_to_search = user_email or 'globistaan@gmail.com'
                user_role = await conn.fetchval(
                    """SELECT urm.user_role_id
                       FROM user_role_mapping urm
                       JOIN users u ON urm.user_id = u.id
                       WHERE u.email = $1 AND urm.role_id = $2 LIMIT 1""",
                    email_to_search, admin_role
                )

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
        file_search_metadata: Dict[str, Any] = None,
        user_role_id: int = None
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

        query = """
            INSERT INTO scraped_websites (
                parent_id, original_url, processing_status,
                gemini_file_name, metadata, depth, user_role_id,
                created_at, updated_at
            ) VALUES (
                $1, $2, $3,
                $4, $5::jsonb, $6, $7,
                NOW(), NOW()
            ) RETURNING id
        """

        params = [
            parent_id,
            page_url,
            'completed' if gemini_file_name else 'processing',
            gemini_file_name,
            json.dumps(file_search_metadata) if file_search_metadata else None,
            1,  # depth = 1 (child of root)
            user_role_id
        ]

        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchval(query, *params)
                logger.info(f"✅ [CHILD_PAGE_SUCCESS] Recorded child page with ID: {result}")
                logger.log_db_query(query, params, result)
                return int(result) if result else None
        except Exception as e:
            logger.error(f"❌ [CHILD_PAGE_ERROR] Failed to record child page: {e}")
            logger.error(f"   URL: {page_url}")
            logger.error(f"   Parent ID: {parent_id}")
            logger.log_db_query(query, params, error=e)
            return None
