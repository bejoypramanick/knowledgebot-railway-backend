"""
Web Crawl Data Access Object
Handles database operations for website scraping only
"""
from typing import Any, Dict, List, Optional
import json

from shared.db import get_db_connection
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("webcrawl_dao", "knowledgebase-ingestion")

class WebCrawlDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def create_website_record(self, url: str, user_role_id: int = None, task_id: str = None) -> Optional[int]:
        """Create website record with pending status."""
        import json
        from urllib.parse import urlparse

        # Determine source type based on URL structure
        # Priority: sitemap > domain only > specific page
        parsed_url = urlparse(url)
        path = parsed_url.path.strip('/')
        domain = parsed_url.netloc or url  # Extract domain from URL
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
            source_type = "sitemap"
        elif not path:
            # Domain only (https://www.globistaan.com or https://www.globistaan.com/) → "website"
            source_type = "website"
        else:
            # With path (https://www.globistaan.com/index.html or /about) → "single"
            source_type = "single"

        # Build metadata for audit trail
        metadata = {
            "scraping_config": {
                "source": source_type  # "sitemap", "website", or "single"
            }
        }

        query = """
            INSERT INTO scraped_websites (original_url, domain, processing_status, user_role_id, celery_task_id, metadata, created_at, updated_at)
            VALUES ($1, $2, 'pending', $3, $4, $5::jsonb, NOW(), NOW())
            RETURNING id
        """
        params = [url, domain, user_role_id, task_id, json.dumps(metadata)]

        try:
            logger.log_db_operation(query, params)
            logger.info(f"🌐 [WEB_CREATE] Creating website record")
            logger.info(f"   URL: {url}")
            logger.info(f"   Domain: {domain}")
            logger.info(f"   Source Type: {source_type}")
            logger.info(f"   User Role ID: {user_role_id}")
            logger.info(f"   Task ID: {task_id}")

            async with get_db_connection() as conn:
                result = await conn.fetchval(query, url, domain, user_role_id, task_id, json.dumps(metadata))
                logger.log_db_query(query, params, result)

                if result:
                    logger.info(f"✅ [WEB_CREATE_SUCCESS] Website record created with ID: {result}")

                return result

        except Exception as e:
            logger.error(f"❌ [WEB_CREATE_ERROR] Failed to create website record: {e}")
            logger.log_db_query(query, params, error=e)
            return None

    async def get_website_by_id(self, website_id: int) -> Optional[Dict[str, Any]]:
        """Get website record by ID."""
        query = """
            SELECT id, original_url, processing_status, error_message, created_at, updated_at
            FROM scraped_websites WHERE id = $1
        """
        params = {"website_id": website_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, website_id)
                logger.log_db_query(query, params, result)
                if result:
                    return {
                        "id": str(result['id']),
                        "original_url": result['original_url'],
                        "processing_status": result['processing_status'],
                        "error_message": result['error_message'],
                        "created_at": result['created_at'],
                        "updated_at": result['updated_at']
                    }
                return None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def get_all_websites(self) -> List[Dict[str, Any]]:
        """Get all websites with their status (excludes deleted records)."""
        query = """
            SELECT id, original_url, processing_status, error_message, created_at, updated_at
            FROM scraped_websites
            WHERE processing_status != 'deleted'
            ORDER BY updated_at DESC
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, result=result)
                return result
        except Exception as e:
            logger.log_db_query(query, error=e)
            return []

    async def get_pending_websites(self) -> List[Dict[str, Any]]:
        """Get all websites with pending or processing status."""
        query = """
            SELECT id, original_url, processing_status, error_message, created_at, updated_at
            FROM scraped_websites
            WHERE processing_status IN ('pending', 'processing')
            ORDER BY updated_at DESC
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.fetch(query)
                logger.log_db_query(query, result=result)
                return result
        except Exception as e:
            logger.log_db_query(query, error=e)
            return []

    async def update_website_status(self, website_id: int, status: str, error_message: str = None) -> bool:
        """Update website processing status."""
        query = """
            UPDATE scraped_websites
            SET processing_status = $2, error_message = $3, updated_at = NOW()
            WHERE id = $1
        """
        params = [website_id, status, error_message]
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, website_id, status, error_message)
                logger.log_db_query(query, params, result)
                return result != "UPDATE 0"
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False

    async def cancel_websites(self) -> int:
        """Cancel all pending/processing websites."""
        query = """
            UPDATE scraped_websites 
            SET processing_status = 'cancelled', updated_at = NOW()
            WHERE processing_status IN ('pending', 'processing')
        """
        try:
            logger.log_db_operation(query)
            async with get_db_connection() as conn:
                result = await conn.execute(query)
                logger.log_db_query(query, result=result)
                return result
        except Exception as e:
            logger.log_db_query(query, error=e)
            return 0

    async def delete_website_by_id(self, website_id: int) -> bool:
        """Delete website record by ID."""
        query = "DELETE FROM scraped_websites WHERE id = $1"
        params = {"website_id": website_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, website_id)
                logger.log_db_query(query, params, result)
                return result != "DELETE 0"
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False

    async def update_celery_task_id(self, website_id: int, task_id: str) -> bool:
        """Update celery_task_id for a website record."""
        query = """
            UPDATE scraped_websites
            SET celery_task_id = $2, updated_at = NOW()
            WHERE id = $1
        """
        params = [website_id, task_id]
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.execute(query, website_id, task_id)
                logger.log_db_query(query, params, result)
                return result != "UPDATE 0"
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False

    async def get_website_details_by_task_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get website details by celery_task_id for worker processing."""
        query = """
            SELECT id, original_url, processing_status, user_email, celery_task_id
            FROM scraped_websites
            WHERE celery_task_id = $1
        """
        params = {"task_id": task_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_connection() as conn:
                result = await conn.fetchrow(query, task_id)
                logger.log_db_query(query, params, result)
                if result:
                    return {
                        "website_id": result['id'],
                        "original_url": result['original_url'],
                        "processing_status": result['processing_status'],
                        "user_email": result['user_email'],
                        "celery_task_id": result['celery_task_id']
                    }
                return None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def get_hierarchical_websites(self) -> List[Dict[str, Any]]:
        """
        Get all websites with hierarchical structure (parent-child relationships).
        Returns only root-level websites (parent_id IS NULL) with their children recursively populated.
        """
        logger.info("🌳 [TREE_START] get_hierarchical_websites() called")

        query = """
            SELECT
                id,
                original_url,
                depth,
                parent_id,
                domain,
                title,
                pages_scraped,
                file_size,
                metadata,
                processing_status,
                error_message,
                created_at,
                updated_at,
                celery_task_id,
                char_count
            FROM scraped_websites
            WHERE parent_id IS NULL AND processing_status != 'deleted'
            ORDER BY depth ASC, created_at DESC
        """
        try:
            logger.info(f"📋 [TREE_QUERY] Fetching root websites (parent_id IS NULL)")
            logger.log_db_operation(query)

            async with get_db_connection() as conn:
                root_websites = await conn.fetch(query)
                logger.info(f"✅ [TREE_RESULTS] Found {len(root_websites)} root websites")
                logger.log_db_query(query, result=root_websites)

                # Build hierarchy by fetching children for each root
                hierarchical_websites = []
                for idx, root in enumerate(root_websites, 1):
                    logger.info(f"🔄 [TREE_BUILD] Processing root {idx}/{len(root_websites)}: ID={root['id']}, URL={root['original_url']}")

                    website_dict = self._format_website_record(root)
                    logger.info(f"📝 [TREE_FORMAT] Formatted root website: {website_dict.get('id')} -> {website_dict.get('url')}")

                    children = await self._get_website_children(conn, root['id'])
                    logger.info(f"👶 [TREE_CHILDREN] Fetched {len(children)} children for root ID={root['id']}")

                    website_dict['children'] = children
                    hierarchical_websites.append(website_dict)

                logger.info(f"✨ [TREE_COMPLETE] Built complete hierarchy with {len(hierarchical_websites)} roots")
                return hierarchical_websites

        except Exception as e:
            logger.error(f"❌ [TREE_ERROR] Error building hierarchical websites: {e}")
            logger.log_db_query(query, error=e)
            return []

    async def _get_website_children(self, conn, parent_id: int, level: int = 0) -> List[Dict[str, Any]]:
        """
        Recursively fetch all children of a website.
        """
        query = """
            SELECT
                id,
                original_url,
                depth,
                parent_id,
                domain,
                title,
                pages_scraped,
                file_size,
                metadata,
                processing_status,
                error_message,
                created_at,
                updated_at,
                celery_task_id,
                char_count
            FROM scraped_websites
            WHERE parent_id = $1 AND processing_status != 'deleted'
            ORDER BY depth ASC, created_at ASC
        """
        try:
            children = await conn.fetch(query, parent_id)

            # Recursively fetch children of children
            result = []
            for child in children:
                child_dict = self._format_website_record(child)
                grandchildren = await self._get_website_children(conn, child['id'], level + 1)
                child_dict['children'] = grandchildren
                result.append(child_dict)

            return result
        except Exception as e:
            logger.error(f"Error fetching children for parent_id {parent_id}: {e}")
            return []

    def _format_website_record(self, record) -> Dict[str, Any]:
        """Format a website record for API response."""
        # Safely handle metadata - could be None, dict, or string
        metadata = {}
        if record['metadata']:
            if isinstance(record['metadata'], dict):
                metadata = record['metadata']
            elif isinstance(record['metadata'], str):
                try:
                    import json
                    metadata = json.loads(record['metadata'])
                except (json.JSONDecodeError, ValueError):
                    metadata = {}

        # Determine file_type based on URL and metadata
        url = record['original_url'].lower()
        is_sitemap = (
            url.endswith('sitemap.xml') or
            url.endswith('sitemap.xml.gz') or
            url.endswith('sitemap_index.xml') or
            '/sitemap' in url and (url.endswith('.xml') or url.endswith('.xml.gz')) or
            'sitemap' in url and url.endswith('.xml')
        )
        
        # Extract source type from metadata
        scraping_config = metadata.get('scraping_config', {}) if metadata else {}
        source_type = scraping_config.get('source')
        
        # Map to display type
        if is_sitemap or source_type == "sitemap":
            file_type = "SITEMAP"
        elif source_type == "single":
            file_type = "WEBPAGE"
        else:
            file_type = "WEBSITE"

        return {
            "id": record['id'],
            "url": record['original_url'],
            "depth": record['depth'] or 0,
            "parent_id": record['parent_id'],
            "domain": record['domain'],
            "title": record['title'],
            "pages_scraped": record['pages_scraped'] or 0,
            "size_bytes": record['file_size'] or 0,
            "char_count": record["char_count"] or 0,
            "processing_status": record['processing_status'],
            "error_message": record['error_message'],
            "created_at": record['created_at'].isoformat() if record['created_at'] else None,
            "updated_at": record['updated_at'].isoformat() if record['updated_at'] else None,
            "celery_task_id": record['celery_task_id'],
            "scraping_config": scraping_config,
            "file_type": file_type,  # Add file_type for UI display
            "children": []  # Will be populated by caller
        }
