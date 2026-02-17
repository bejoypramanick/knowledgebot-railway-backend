"""
AI Service for Website Crawling
Handles uploading scraped content to Gemini FileSearch
"""
import asyncio
import os
import tempfile
import time
from datetime import datetime
from typing import Any, Dict, List, Optional
from urllib.parse import urlparse

from google.genai import types

from shared.otel_logger import get_otel_logger
from shared.file_search import get_file_search_store_by_display_name
from website_crawling.core.ai import get_genai_client
from website_crawling.core.config import settings
from website_crawling.service.website_service import WebsiteService
from website_crawling.dao.scraping_dao import ScrapingDAO

logger = get_otel_logger("ai_service", "website-crawling")


async def upload_content_to_gemini(
    content: str,
    url: str,
    title: str,
    user_email: str = None,
    page_depth: int = 0
) -> Dict[str, Any]:
    """
    Upload scraped content directly to Gemini FileSearch store.

    Args:
        content: The scraped text content
        url: Original URL that was scraped
        title: Page title
        user_email: User email for metadata
        page_depth: Depth of page in crawl hierarchy

    Returns:
        Dict with upload result including file name and state
    """
    genai_client = get_genai_client()
    if not genai_client:
        logger.error("❌ Gemini client not available")
        raise Exception("Gemini client not configured")

    # Get FileSearch store display name from config
    store_display_name = settings.gemini_file_search_store_name
    if not store_display_name:
        logger.error("❌ GEMINI_FILE_SEARCH_STORE_NAME not configured")
        raise Exception("GEMINI_FILE_SEARCH_STORE_NAME environment variable is required")

    logger.info(f"📦 Looking up FileSearch store: {store_display_name}")

    # Look up store by display name
    file_search_store_name = get_file_search_store_by_display_name(
        genai_client,
        display_name=store_display_name
    )

    if not file_search_store_name:
        logger.error(f"❌ FileSearch store '{store_display_name}' not found")
        raise Exception(f"FileSearch store '{store_display_name}' not found")

    temp_path = None
    try:
        # Create a temporary file for the content
        fd, temp_path = tempfile.mkstemp(suffix='.md')
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            # Add title and URL at the top
            if title:
                f.write(f"# {title}\n\n")
            if url:
                f.write(f"Source URL: {url}\n\n")
            f.write(content)

        # Clean URL for filename
        clean_url = url.replace('https://', '').replace('http://', '')
        clean_url = clean_url.replace('/', '_').replace(':', '_').replace('?', '_')
        clean_url = clean_url[:50]
        temp_filename = f"scraped_{clean_url}_{datetime.now().strftime('%Y%m%d_%H%M%S')}.md"

        logger.info(f"📤 Uploading to FileSearch store: {file_search_store_name}")

        # Upload directly to FileSearch store (no fallback)
        operation = genai_client.file_search_stores.upload_to_file_search_store(
            file=temp_path,
            file_search_store_name=file_search_store_name,
            config={
                'display_name': temp_filename,
                'custom_metadata': [
                    {'key': 'original_url', 'string_value': url},
                    {'key': 'user_email', 'string_value': user_email or 'admin'},
                    {'key': 'page_type', 'string_value': 'scraped_page'},
                    {'key': 'source', 'string_value': 'website_scraping'},
                    {'key': 'page_depth', 'string_value': str(page_depth)}
                ]
            }
        )

        if not operation:
            raise Exception("Failed to create FileSearch upload operation")

        # Poll for operation completion
        final_state = "PENDING"
        gemini_processed_at = None
        document_name = None

        for i in range(15):  # Poll for up to 30 seconds
            current_operation = genai_client.operations.get(operation)
            if not current_operation:
                logger.warning(f"🔄 [GEMINI] Poll attempt {i+1}: Operation is None")
                await asyncio.sleep(2)
                continue

            # Check for document_name in response
            resp = getattr(current_operation, 'response', None)
            if resp and hasattr(resp, 'document_name') and resp.document_name:
                final_state = "ACTIVE"
                document_name = resp.document_name
                gemini_processed_at = datetime.utcnow()
                logger.info(f"✅ [GEMINI] FileSearch upload complete - Document: {document_name}")
                break

            # Check for state in operation
            top_state = getattr(current_operation, 'state', None)
            if top_state:
                final_state = getattr(top_state, 'name', str(top_state))
                logger.info(f"🔄 [GEMINI] FileSearch operation state (Attempt {i+1}/15): {final_state}")
                if final_state == "ACTIVE":
                    gemini_processed_at = datetime.utcnow()
                    break

            await asyncio.sleep(2)

        if not document_name:
            raise Exception(f"FileSearch upload failed - final state: {final_state}")

        return {
            "success": final_state == "ACTIVE",
            "file_name": document_name,
            "state": final_state,
            "processed_at": gemini_processed_at.isoformat() if gemini_processed_at else None,
            "file_search_metadata": {
                "type": "file_search",
                "file_search_store_name": file_search_store_name,
                "document_name": document_name,
                "original_url": url,
                "page_type": "scraped_page",
                "uploaded_at": gemini_processed_at.isoformat() if gemini_processed_at else None
            }
        }

    except Exception as e:
        logger.error(f"❌ Error uploading to FileSearch: {e}")
        import traceback
        logger.error(f"❌ Full traceback: {traceback.format_exc()}")
        raise

    finally:
        if temp_path and os.path.exists(temp_path):
            try:
                os.unlink(temp_path)
            except:
                pass


async def record_scraped_metadata(
    url: str,
    domain: str,
    title: str,
    content_length: int,
    pages_scraped: int,
    gemini_file_name: str,
    gemini_file_uri: str,
    gemini_state: str,
    scraped_urls: List[str],
    scraping_config: Dict[str, Any],
    file_search_metadata: Dict[str, Any] = None,
    version: int = 1,
    user_id: str = None,
    parent_id: Optional[int] = None,
    depth: int = 0,
    crawl_session_id: Optional[str] = None,
    celery_task_id: Optional[str] = None
) -> Optional[str]:
    """
    Record scraped website metadata to database.

    Args:
        file_search_metadata: FileSearch store metadata for deletion (contains store_name, document_name)

    Returns:
        Record ID if successful, None otherwise
    """
    try:
        website_service = WebsiteService()

        # Get admin user_role_id (same logic as file uploads)
        # NOTE: user_role_id is nullable in the database, so we can proceed without it
        admin_user_role_id = await get_admin_user_role_id()
        if not admin_user_role_id:
            logger.warning("⚠️ Could not find admin user_role_id - scraped websites will have NULL user_role_id")
            admin_user_role_id = None  # Allow NULL value

        # Extract targeting patterns from scraping config
        include_patterns = scraping_config.get("include_patterns", []) if scraping_config else []
        exclude_patterns = scraping_config.get("exclude_patterns", []) if scraping_config else []

        metadata = {
            "user_role_id": admin_user_role_id,  # Can be None (user_role_id is nullable)
            "url": url,
            "domain": domain,
            "title": title,
            "description": f"Scraped from {url}",
            "content_length": content_length,
            "pages_scraped": pages_scraped,
            "status": gemini_state if gemini_state else "pending",
            "gemini_file_name": gemini_file_name,
            "gemini_file_uri": gemini_file_uri,
            "parent_id": parent_id,
            "depth": depth,  # Use the parameter
            "crawl_session_id": crawl_session_id,
            "celery_task_id": celery_task_id,  # Store Celery task ID for tracking
            # Targeting patterns used for this crawl
            "crawl_patterns": {
                "include_patterns": include_patterns,
                "exclude_patterns": exclude_patterns
            }
        }

        # Add FileSearch metadata if available
        if file_search_metadata:
            metadata["file_search_metadata"] = file_search_metadata
            logger.info(f"📝 [METADATA] Storing FileSearch info: store={file_search_metadata.get('file_search_store_name')}, document={file_search_metadata.get('document_name')}")

        # Log targeting patterns if present
        if include_patterns or exclude_patterns:
            logger.info(f"🎯 [METADATA] Storing crawl patterns: include={len(include_patterns)}, exclude={len(exclude_patterns)}")

        # Use ScrapingDAO to record metadata
        scraping_dao = ScrapingDAO()
        record_id = await scraping_dao.record_scraped_metadata(metadata)
        logger.info(f"✅ Scraped metadata recorded: {record_id}")
        return record_id

    except Exception as e:
        logger.error(f"❌ Failed to persist scraped metadata: {e}")
        return None


async def get_admin_user_role_id() -> Optional[str]:
    """Get user_role_id for admin role - same logic as file uploads"""
    try:
        from shared.db import get_db_connection
        
        async with get_db_connection() as conn:
            # First get the admin role ID
            admin_role = await conn.fetchrow(
                "SELECT id FROM roles WHERE role_name = 'admin'"
            )
            
            if not admin_role:
                logger.error("Admin role not found in roles table")
                return None
            
            admin_role_id = admin_role['id']
            
            # Check if user has admin role mapping (use a default admin user)
            admin_mapping = await conn.fetchrow(
                """SELECT user_role_id 
                   FROM user_role_mapping 
                   WHERE role_id = $1 AND is_active = true
                   LIMIT 1""",
                admin_role_id
            )
            
            if admin_mapping:
                logger.info(f"Using admin user_role_id: {admin_mapping['user_role_id']}")
                return admin_mapping['user_role_id']
            else:
                logger.warning("No admin user_role_mapping found - scraped websites may not be saved")
                return None
            
    except Exception as e:
        logger.error(f"Error getting admin user role ID: {e}")
        return None
