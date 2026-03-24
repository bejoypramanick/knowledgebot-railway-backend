"""
Web Crawl Data Access Object
Handles database operations for website scraping only
"""
from typing import Any, Dict, List, Optional
import json

from sqlalchemy import text
from shared.sqlalchemy_db import get_db_session
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("webcrawl_dao", "knowledgebase-ingestion")

class WebCrawlDAO:
    def __init__(self):
        pass  # No connection parameter - DAO manages its own connection

    async def create_website_record(self, url: str, user_role_id: str = None, task_id: str = None) -> Optional[str]:
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
            VALUES (:url, :domain, 'pending', :user_role_id, :task_id, CAST(:metadata AS jsonb), NOW(), NOW())
            RETURNING id
        """
        params = {
            "url": url,
            "domain": domain,
            "user_role_id": user_role_id,
            "task_id": task_id,
            "metadata": json.dumps(metadata)
        }

        try:
            logger.log_db_operation(query, params)
            logger.info(f"🌐 [WEB_CREATE] Creating website record")
            logger.info(f"   URL: {url}")
            logger.info(f"   Domain: {domain}")
            logger.info(f"   Source Type: {source_type}")
            logger.info(f"   User Role ID: {user_role_id}")
            logger.info(f"   Task ID: {task_id}")

            async with get_db_session() as session:
                result = (await session.execute(text(query), params)).scalar()
                logger.log_db_query(query, params, result)
                await session.commit()

                if result:
                    logger.info(f"✅ [WEB_CREATE_SUCCESS] Website record created with ID: {result}")

                return result

        except Exception as e:
            logger.error(f"❌ [WEB_CREATE_ERROR] Failed to create website record: {e}")
            logger.log_db_query(query, params, error=e)
            return None

    async def get_website_by_id(self, website_id: str) -> Optional[Dict[str, Any]]:
        """Get website record by ID."""
        query = """
            SELECT id, original_url, processing_status, error_message, created_at, updated_at
            FROM scraped_websites WHERE id = :website_id
        """
        params = {"website_id": website_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = (await session.execute(text(query), params)).fetchone()
                logger.log_db_query(query, params, result)
                if result:
                    return {
                        "id": str(result.id),
                        "original_url": result.original_url,
                        "processing_status": result.processing_status,
                        "error_message": result.error_message,
                        "created_at": result.created_at,
                        "updated_at": result.updated_at
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
            async with get_db_session() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
                logger.log_db_query(query, result=rows)
                return [dict(row._mapping) for row in rows]
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
            async with get_db_session() as session:
                result = await session.execute(text(query))
                rows = result.fetchall()
                logger.log_db_query(query, result=rows)
                return [dict(row._mapping) for row in rows]
        except Exception as e:
            logger.log_db_query(query, error=e)
            return []

    async def update_website_status(self, website_id: str, status: str, error_message: str = None) -> bool:
        """Update website processing status."""
        query = """
            UPDATE scraped_websites
            SET processing_status = :status, error_message = :error_message, updated_at = NOW()
            WHERE id = :website_id
        """
        params = {"website_id": website_id, "status": status, "error_message": error_message}
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, "UPDATE 1")
                return result.rowcount > 0
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
            async with get_db_session() as session:
                result = await session.execute(text(query))
                await session.commit()
                affected_rows = result.rowcount
                logger.log_db_query(query, result=f"UPDATE {affected_rows}")
                return affected_rows
        except Exception as e:
            logger.log_db_query(query, error=e)
            return 0

    async def delete_website_by_id(self, website_id: str) -> bool:
        """Delete website record by ID."""
        query = "DELETE FROM scraped_websites WHERE id = :website_id"
        params = {"website_id": website_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, "DELETE 1")
                return result.rowcount > 0
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False

    async def update_celery_task_id(self, website_id: str, task_id: str) -> bool:
        """Update celery_task_id for a website record."""
        query = """
            UPDATE scraped_websites
            SET celery_task_id = :task_id, updated_at = NOW()
            WHERE id = :website_id
        """
        params = {"website_id": website_id, "task_id": task_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = await session.execute(text(query), params)
                await session.commit()
                logger.log_db_query(query, params, "UPDATE 1")
                return result.rowcount > 0
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return False

    async def get_website_details_by_task_id(self, task_id: str) -> Optional[Dict[str, Any]]:
        """Get website details by celery_task_id for worker processing."""
        query = """
            SELECT id, original_url, processing_status, user_role_id, celery_task_id
            FROM scraped_websites
            WHERE celery_task_id = :task_id
        """
        params = {"task_id": task_id}
        try:
            logger.log_db_operation(query, params)
            async with get_db_session() as session:
                result = (await session.execute(text(query), params)).fetchone()
                logger.log_db_query(query, params, result)
                if result:
                    return {
                        "website_id": result.id,
                        "original_url": result.original_url,
                        "processing_status": result.processing_status,
                        "user_role_id": result.user_role_id,
                        "celery_task_id": result.celery_task_id
                    }
                return None
        except Exception as e:
            logger.log_db_query(query, params, error=e)
            return None

    async def get_hierarchical_websites(self, include_inactive: bool = False, user_role_id: str = None) -> List[Dict[str, Any]]:
        """
        Get all websites with hierarchical structure (parent-child relationships).
        Returns only root-level websites (parent_id IS NULL) with their children recursively populated.

        Args:
            include_inactive: If False (default), returns pending, processing, queued, and completed items.
                            If True, returns items that are NOT pending, processing, queued, and NOT completed.
            user_role_id: Optional user role ID to filter by.
        """
        logger.info(f"🌳 [TREE_START] get_hierarchical_websites(user_role_id={user_role_id}) called")

        # Build WHERE clause based on include_inactive flag
        where_clause = "WHERE is_root_page = true"
        params = {}

        if user_role_id:
            where_clause += " AND user_role_id = :user_role_id"
            params["user_role_id"] = user_role_id

        if not include_inactive:
            # Active: pending, processing, queued, and completed
            where_clause += " AND processing_status IN ('pending', 'processing', 'queued', 'completed')"
        else:
            # Not Active: everything except pending, processing, queued, and completed
            where_clause += " AND processing_status NOT IN ('pending', 'processing', 'queued', 'completed')"

        query = f"""
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
                char_count,
                processed_content_s3_key
            FROM scraped_websites
            {where_clause}
            ORDER BY depth ASC, id DESC
        """
        try:
            logger.info(f"📋 [TREE_QUERY] Fetching root websites (parent_id IS NULL)")
            logger.log_db_operation(query)

            async with get_db_session() as session:
                root_websites_result = await session.execute(text(query), params)
                root_websites = root_websites_result.fetchall()
                logger.info(f"✅ [TREE_RESULTS] Found {len(root_websites)} root websites")
                logger.log_db_query(query, result=root_websites)

                # Build hierarchy by fetching children for each root
                hierarchical_websites = []
                for idx, root in enumerate(root_websites, 1):
                    logger.info(f"🔄 [TREE_BUILD] Processing root {idx}/{len(root_websites)}: ID={root.id}, URL={root.original_url}")

                    website_dict = self._format_website_record(root)
                    logger.info(f"📝 [TREE_FORMAT] Formatted root website: {website_dict.get('id')} -> {website_dict.get('url')}")

                    children = await self._get_website_children(session, root.id, include_inactive=include_inactive, user_role_id=user_role_id)
                    logger.info(f"👶 [TREE_CHILDREN] Fetched {len(children)} children for root ID={root.id}")

                    website_dict['children'] = children
                    hierarchical_websites.append(website_dict)

                logger.info(f"✨ [TREE_COMPLETE] Built complete hierarchy with {len(hierarchical_websites)} roots")

                # For Not Active tab, also fetch orphan/deleted child pages
                if include_inactive:
                    logger.info("🔍 [ORPHAN_CHECK] Checking for orphan/deleted child pages")
                    orphan_where = "WHERE parent_id IS NOT NULL AND processing_status NOT IN ('pending', 'processing', 'queued', 'completed')"
                    if user_role_id:
                        orphan_where += " AND user_role_id = :user_role_id"

                    orphan_query = f"""
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
                            char_count,
                            processed_content_s3_key
                        FROM scraped_websites
                        {orphan_where}
                        ORDER BY id DESC
                    """
                    orphan_pages_result = await session.execute(text(orphan_query), params)
                    orphan_pages = orphan_pages_result.fetchall()
                    logger.info(f"✅ [ORPHAN_RESULTS] Found {len(orphan_pages)} orphan/deleted child pages")

                    # Add orphan pages as root-level items (without parent)
                    for orphan in orphan_pages:
                        orphan_dict = self._format_website_record(orphan)
                        orphan_dict['children'] = []  # Orphans have no children in this view
                        orphan_dict['is_orphan'] = True  # Mark as orphan for UI
                        hierarchical_websites.append(orphan_dict)

                    logger.info(f"✨ [TREE_WITH_ORPHANS] Total items (roots + orphans): {len(hierarchical_websites)}")

                return hierarchical_websites

        except Exception as e:
            logger.error(f"❌ [TREE_ERROR] Error building hierarchical websites: {e}")
            logger.log_db_query(query, error=e)
            return []

    async def _get_website_children(self, session, parent_id: str, level: int = 0, include_inactive: bool = False, user_role_id: str = None) -> List[Dict[str, Any]]:
        """
        Recursively fetch all children of a website.

        Args:
            include_inactive: If False (default), returns pending, processing, queued, and completed items.
                            If True, returns items that are NOT pending, processing, queued, and NOT completed.
            user_role_id: Optional user role ID to filter by.
        """
        # Build WHERE clause based on include_inactive flag
        where_clause = "WHERE parent_id = :parent_id"
        params = {"parent_id": parent_id}

        if user_role_id:
            where_clause += " AND user_role_id = :user_role_id"
            params["user_role_id"] = user_role_id

        if not include_inactive:
            # Active: pending, processing, queued, and completed
            where_clause += " AND processing_status IN ('pending', 'processing', 'queued', 'completed')"
        else:
            # Not Active: everything except pending, processing, queued, and completed
            where_clause += " AND processing_status NOT IN ('pending', 'processing', 'queued', 'completed')"

        query = f"""
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
                char_count,
                processed_content_s3_key
            FROM scraped_websites
            {where_clause}
            ORDER BY depth ASC, id ASC
        """
        try:
            children_result = await session.execute(text(query), params)
            children = children_result.fetchall()

            # Recursively fetch children of children
            result = []
            for child in children:
                child_dict = self._format_website_record(child)
                grandchildren = await self._get_website_children(session, child.id, level + 1, include_inactive=include_inactive, user_role_id=user_role_id)
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
        if record.metadata:
            if isinstance(record.metadata, dict):
                metadata = record.metadata
            elif isinstance(record.metadata, str):
                try:
                    import json
                    metadata = json.loads(record.metadata)
                except (json.JSONDecodeError, ValueError):
                    metadata = {}

        # Determine file_type based on URL and metadata
        url = record.original_url.lower()
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
            "id": record.id,
            "url": record.original_url,
            "source": "scrape",  # Add source field for UI filtering
            "depth": record.depth or 0,
            "parent_id": record.parent_id,
            "domain": record.domain,
            "title": record.title,
            "pages_scraped": record.pages_scraped or 0,
            "size_bytes": record.file_size or 0,
            "char_count": record.char_count or 0,
            "processing_status": record.processing_status,
            "error_message": record.error_message,
            "created_at": record.created_at.isoformat() if record.created_at else None,
            "updated_at": record.updated_at.isoformat() if record.updated_at else None,
            "celery_task_id": record.celery_task_id,
            "processed_content_s3_key": record.processed_content_s3_key,
            "scraping_config": scraping_config,
            "file_type": file_type,  # Add file_type for UI display
            "children": []  # Will be populated by caller
        }
