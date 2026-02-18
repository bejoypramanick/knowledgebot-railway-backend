"""
Website Service Layer for Website Crawling
Provides business logic for website scraping and crawling operations with session management
"""
import asyncio
import os
import time
import re
import uuid
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse, urljoin, urlunparse
from datetime import datetime

from shared.otel_logger import get_otel_logger
from website_crawling.core.config import settings
from website_crawling.dao.scraping_dao import ScrapingDAO
from website_crawling.utils.links import extract_links_from_result
from website_crawling.service.docling_integration import (
    process_html_with_docling,
    should_use_docling_for_website
)

logger = get_otel_logger("website_service", "website-crawling")

# In-memory session storage (in production, use Redis or database)
_active_sessions: Dict[str, Dict[str, Any]] = {}

# Try to import crawl4ai
try:
    from crawl4ai import AsyncWebCrawler
    from crawl4ai.extraction_strategy import NoExtractionStrategy
    CRAWL4AI_AVAILABLE = True
except ImportError:
    logger.warning("crawl4ai not available - using fallback HTTP scraping")
    CRAWL4AI_AVAILABLE = False

# Only Crawl4AI is used for website scraping
    try:
        import crawl4ai
        CRAWL4AI_AVAILABLE = True
    except ImportError:
        CRAWL4AI_AVAILABLE = False


class WebsiteService:
    """Service layer for website scraping and crawling operations"""

    def __init__(self):
        self.scraping_dao = ScrapingDAO()

    async def _check_cancellation(self, celery_task_id: str) -> bool:
        """Check if task has been marked for cancellation via Redis"""
        if not celery_task_id:
            return False

        try:
            import redis as redis_lib
            redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/1')
            redis_conn = redis_lib.from_url(redis_url)

            cancelled_key = f"task_cancelled:{celery_task_id}"
            result = redis_conn.exists(cancelled_key)
            redis_conn.close()

            return bool(result)
        except Exception as e:
            logger.warning(f"⚠️ Error checking cancellation status: {e}")
            return False

    @staticmethod
    def get_parent_url(url: str) -> Optional[str]:
        """
        Extract parent URL by removing last path segment.

        Examples:
            https://example.com/about/team -> https://example.com/about
            https://example.com/about -> https://example.com
            https://example.com -> None (already at root)
        """
        parsed = urlparse(url)
        path_parts = [p for p in parsed.path.split('/') if p]

        if not path_parts:
            # Already at root
            return None
        elif len(path_parts) == 1:
            # Direct child of domain, parent is the root
            return f"{parsed.scheme}://{parsed.netloc}"
        else:
            # Remove last path segment
            parent_path = '/'.join(path_parts[:-1])
            return f"{parsed.scheme}://{parsed.netloc}/{parent_path}"

    @staticmethod
    def should_include_url(url: str, include_patterns: List[str], exclude_patterns: List[str]) -> bool:
        """
        Check if a URL should be included based on include/exclude patterns.

        Args:
            url: The URL to check
            include_patterns: List of regex patterns - URL must match at least one (if list is non-empty)
            exclude_patterns: List of regex patterns - URL must not match any

        Returns:
            True if URL should be included, False otherwise
        """
        # Check exclude patterns first (faster to fail)
        for pattern in exclude_patterns:
            try:
                if re.search(pattern, url):
                    logger.debug(f"🚫 URL excluded by pattern '{pattern}': {url}")
                    return False
            except re.error as e:
                logger.warning(f"⚠️ Invalid exclude pattern '{pattern}': {e}")

        # Check include patterns (only if provided)
        if include_patterns:
            for pattern in include_patterns:
                try:
                    if re.search(pattern, url):
                        logger.debug(f"✓ URL included by pattern '{pattern}': {url}")
                        return True
                except re.error as e:
                    logger.warning(f"⚠️ Invalid include pattern '{pattern}': {e}")
            # If include patterns are provided and URL doesn't match any, exclude it
            logger.debug(f"🚫 URL doesn't match any include pattern: {url}")
            return False

        # No include patterns specified, and URL passed exclude patterns
        return True

    async def get_crawl_patterns(self, website_id: int) -> Dict[str, List[str]]:
        """
        Retrieve the targeting patterns used when a website was crawled.
        Useful for re-crawling with the same patterns.

        Args:
            website_id: ID of the scraped website record

        Returns:
            Dict with include_patterns and exclude_patterns
        """
        try:
            from shared.db import get_db_connection

            async with get_db_connection() as conn:
                record = await conn.fetchrow(
                    "SELECT metadata FROM scraped_websites WHERE id = $1",
                    website_id
                )

                if not record or not record["metadata"]:
                    logger.debug(f"No metadata found for website ID {website_id}")
                    return {"include_patterns": [], "exclude_patterns": []}

                metadata = record["metadata"]
                crawl_patterns = metadata.get("crawl_patterns", {})

                return {
                    "include_patterns": crawl_patterns.get("include_patterns", []),
                    "exclude_patterns": crawl_patterns.get("exclude_patterns", [])
                }

        except Exception as e:
            logger.error(f"❌ Failed to retrieve crawl patterns for website {website_id}: {e}")
            return {"include_patterns": [], "exclude_patterns": []}

    @staticmethod
    def clean_content(content: str) -> str:
        """
        Remove navigation elements, search boxes, and redundant links from scraped content.

        Removes:
        - Jump to content links (e.g., [Jump to content](#bodyContent))
        - Search this site prompts
        - Navigation menus and headers
        - Skip to main content links
        - Advertisement sections
        - Social media follow buttons
        - Subscribe prompts

        Args:
            content: Raw HTML or markdown content from scraper

        Returns:
            Cleaned content with navigation artifacts removed
        """
        if not content:
            return content

        # Remove markdown-style jump links (e.g., [Jump to content](url))
        content = re.sub(r'\[\s*(?:Jump|Skip|Go)\s+(?:to\s+)?(?:content|main|body|article|text)\s*\]\s*\([^)]*\)', '', content, flags=re.IGNORECASE)

        # Remove "Search this site" and similar prompts
        content = re.sub(r'Search\s+(?:this\s+)?site.*?(?:\n|$)', '', content, flags=re.IGNORECASE | re.MULTILINE)
        content = re.sub(r'Search\s+the\s+site.*?(?:\n|$)', '', content, flags=re.IGNORECASE | re.MULTILINE)

        # Remove navigation section markers (common patterns)
        content = re.sub(r'--- Navigation.*?---', '', content, flags=re.IGNORECASE)
        content = re.sub(r'--- Menu.*?---', '', content, flags=re.IGNORECASE)
        content = re.sub(r'--- Header.*?---', '', content, flags=re.IGNORECASE)

        # Remove "Subscribe" and "Follow" prompts
        content = re.sub(r'(?:Subscribe|Follow|Sign up).*?(?:button|now|here).*?(?:\n|$)', '', content, flags=re.IGNORECASE)

        # Remove advertisement markers
        content = re.sub(r'\[(?:AD|Advertisement|Ad)\].*?(?:\n|$)', '', content, flags=re.IGNORECASE)

        # Remove common navigation link patterns
        content = re.sub(r'\[(?:Home|Back|Previous|Next|Top|Up)\]\([^)]*\)', '', content, flags=re.IGNORECASE)

        # Remove multiple consecutive blank lines (keep content compact)
        content = re.sub(r'\n\n\n+', '\n\n', content)

        # Remove leading/trailing whitespace
        content = content.strip()

        return content

    @staticmethod
    def classify_url_type(url: str, crawl4ai_depth: Optional[int] = None) -> str:
        """
        Intelligently classify a URL as sitemap, single page, or website.
        
        If crawl4ai_depth is provided, use it for more accurate classification:
        - depth 0 (root): classify as 'website'
        - depth > 0 (child pages): classify as 'single_page'
        
        Args:
            url: URL to classify
            crawl4ai_depth: Optional depth from crawl4ai during crawling

        Returns:
            One of: 'sitemap', 'single_page', 'website'
        """
        # If crawl4ai depth is available, use it for classification
        if crawl4ai_depth is not None:
            if crawl4ai_depth == 0:
                logger.debug(f"🌐 Classified as website (crawl4ai depth=0): {url}")
                return "website"
            elif crawl4ai_depth > 0:
                logger.debug(f"📄 Classified as single page (crawl4ai depth={crawl4ai_depth}): {url}")
                return "single_page"
        
        # Fall back to static heuristics if crawl4ai depth not available
        url_lower = url.lower()

        # 1) Strong sitemap detection
        try:
            parsed = urlparse(url_lower)
            path = parsed.path or "/"
            filename = path.split("/")[-1]

            # Common sitemap patterns
            sitemap_like = (
                filename == "sitemap.xml"
                or filename.endswith(".xml") and "sitemap" in filename
                or "sitemap=" in (parsed.query or "")
            )
            if sitemap_like:
                logger.debug(f"📋 Classified as sitemap: {url}")
                return "sitemap"
        except Exception:
            # If parsing fails, fall back to simple string check
            if url_lower.endswith(".xml") or "sitemap" in url_lower:
                logger.debug(f"📋 Classified as sitemap (fallback): {url}")
                return "sitemap"

        try:
            parsed = urlparse(url)
            path = parsed.path or "/"
            path_parts = [p for p in path.split('/') if p]
            filename = path_parts[-1] if path_parts else ""

            # 2) Detect single pages by file extension or query-style URLs
            page_exts = {
                "html", "htm", "php", "asp", "aspx", "jsp",
                "pdf", "doc", "docx", "ppt", "pptx",
                "xls", "xlsx", "csv", "txt", "md", "rtf"
            }

            # If there is a dot in the last path segment, try to treat it as a file
            if "." in filename:
                ext = filename.rsplit(".", 1)[-1].lower()
                if ext in page_exts:
                    logger.debug(f"📄 Classified as single page by extension .{ext}: {url}")
                    return "single_page"

            # URLs with query parameters and a non-root path are often individual pages
            if parsed.query and len(path_parts) >= 1:
                logger.debug(f"📄 Classified as single page by query string: {url}")
                return "single_page"

            # 3) Enhanced heuristic by path depth and page patterns:
            # - 0–1 segments: check if it's a specific page vs section
            # - 2–3 segments: could be section or specific page
            # - 4+ segments: more likely a deep content page
            depth = len(path_parts)
            
            # Common single page patterns at depth 1-2 that should be treated as pages, not sections
            single_page_patterns = {
                'contact', 'contact-us', 'about', 'about-us', 'team', 'teams',
                'services', 'service', 'products', 'product', 'portfolio',
                'blog', 'news', 'careers', 'jobs', 'help', 'support',
                'faq', 'terms', 'privacy', 'policy', 'login', 'register',
                'signup', 'search', 'profile', 'account', 'dashboard'
            }
            
            # Check if the last path segment matches single page patterns
            if path_parts:
                last_segment = path_parts[-1].lower().replace('-', '').replace('_', '')
                if last_segment in single_page_patterns:
                    logger.debug(f"📄 Classified as single page by pattern '{last_segment}': {url}")
                    return "single_page"
            
            # Original depth-based logic as fallback
            if depth <= 1:
                # For depth 1, check if it looks like a specific page vs section
                if path_parts and len(path_parts) == 1:
                    segment = path_parts[0].lower()
                    if segment in single_page_patterns:
                        logger.debug(f"📄 Classified as single page (depth 1, pattern '{segment}'): {url}")
                        return "single_page"
                
                logger.debug(f"🌐 Classified as website (root/shallow, depth={depth}): {url}")
                return "website"
            elif depth >= 4:
                logger.debug(f"📄 Classified as single page (deep path, depth={depth}): {url}")
                return "single_page"
            else:
                # For depth 2-3, use additional heuristics
                if path_parts:
                    last_segment = path_parts[-1].lower().replace('-', '').replace('_', '')
                    if last_segment in single_page_patterns:
                        logger.debug(f"📄 Classified as single page (depth {depth}, pattern '{last_segment}'): {url}")
                        return "single_page"
                
                logger.debug(f"🌐 Classified as website (moderate depth={depth}): {url}")
                return "website"
        except Exception as e:
            logger.warning(f"⚠️ Error classifying URL {url}: {e}, defaulting to website")
            return "website"

    async def scrape_website(self, url: str, options: Dict[str, Any], celery_task_id: str = None, website_id: int = None) -> Dict[str, Any]:
        """
        Scrape a website and optionally crawl linked pages.

        Args:
            url: The URL to scrape
            options: Scraping options
            celery_task_id: Celery task ID for cancellation checking
            website_id: Database website ID for status updates

        Returns:
            Dict with scraping results
        """
        start_time = time.perf_counter()

        # Helper function to check if task was cancelled
        async def check_cancellation():
            if not celery_task_id:
                return False
            try:
                import redis as redis_lib
                redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/1')
                redis_conn = redis_lib.from_url(redis_url)
                cancelled_key = f"task_cancelled:{celery_task_id}"
                result = redis_conn.exists(cancelled_key)
                redis_conn.close()
                return bool(result)
            except Exception as e:
                logger.warning(f"⚠️ Error checking cancellation: {e}")
                return False
        max_pages = options.get("max_pages", 1)
        max_depth = options.get("max_depth", 2)
        replace_existing = options.get("replace_existing", False)
        delay_between_requests = options.get("delay_between_requests", 0)
        max_concurrent = options.get("max_concurrent", 10)
        timeout = options.get("timeout", 60)  # Increased from 30 to 60 seconds for better reliability
        include_patterns = options.get("include_patterns", []) or []
        exclude_patterns = options.get("exclude_patterns", []) or []

        # Classify URL type for proper parent-child relationship handling
        url_type = self.classify_url_type(url)
        logger.info(f"🌐 Starting {url_type} scrape for {url} - max_pages={max_pages}, max_depth={max_depth}, delay={delay_between_requests}s, concurrent={max_concurrent}")
        if include_patterns or exclude_patterns:
            logger.info(f"🎯 URL targeting - include: {len(include_patterns)} patterns, exclude: {len(exclude_patterns)} patterns")

        # Check for existing record - skip if called from Celery task (website_id already provided)
        if not website_id:
            existing = await self.scraping_dao.get_existing_website(url)
            if existing and not replace_existing:
                where_exists = ["database"]
                try:
                    import json
                    meta = existing['metadata']
                    if isinstance(meta, str):
                        meta = json.loads(meta)
                    if meta and meta.get('file_search_metadata'):
                        where_exists.append("FileSearch")
                except Exception:
                    pass
                location = " and ".join(where_exists)
                logger.info(f"⚠️ Website already exists in {location}: {url}")
                return {
                    "success": False,
                    "duplicate": True,
                    "error": f"URL already exists in {location}. Delete it first or enable Replace Existing.",
                    "where_exists": where_exists,
                    "existing_record": dict(existing)
                }

            if existing and replace_existing:
                logger.info(f"🔄 Replacing existing website: {url}")
                await self.scraping_dao.delete_website_record(url)

        # Check if this is a sitemap URL
        from website_crawling.utils.sitemap_parser import is_sitemap_url, fetch_and_parse_sitemap

        if is_sitemap_url(url):
            logger.info(f"📄 Detected sitemap URL: {url}")
            # Parse the sitemap and scrape all URLs
            try:
                sitemap_urls = await fetch_and_parse_sitemap(url)
                if not sitemap_urls:
                    return {
                        "success": False,
                        "error": "No URLs found in sitemap or failed to parse sitemap"
                    }

                logger.info(f"📋 Found {len(sitemap_urls)} URLs in sitemap, will scrape up to {max_pages}")

                # Filter URLs based on targeting patterns
                if include_patterns or exclude_patterns:
                    filtered_urls = [
                        u for u in sitemap_urls
                        if self.should_include_url(u, include_patterns, exclude_patterns)
                    ]
                    logger.info(f"🎯 Filtered sitemap URLs: {len(filtered_urls)} out of {len(sitemap_urls)}")
                    urls_to_scrape = filtered_urls[:max_pages]
                else:
                    urls_to_scrape = sitemap_urls[:max_pages]

                # ✅ INTERLEAVED SITEMAP PROCESSING
                # Step 1: Create sitemap parent record first
                logger.info(f"📋 Creating sitemap parent record: {url}")
                crawl_session_id = str(uuid.uuid4())
                sitemap_record_id = await record_scraped_metadata(
                    url=url,
                    domain=urlparse(url).netloc.replace('www.', ''),
                    title=url,  # Use URL as title for sitemap parent
                    content_length=0,  # Sitemap itself isn't counted
                    pages_scraped=len(urls_to_scrape),
                    gemini_file_name=None,
                    gemini_file_uri=None,
                    gemini_state="DISCOVERED",
                    scraped_urls=[url],
                    scraping_config={
                        "max_pages": max_pages,
                        "max_depth": max_depth,
                        "source": "sitemap",
                        "include_patterns": include_patterns,
                        "exclude_patterns": exclude_patterns
                    },
                    file_search_metadata=None,
                    parent_id=None,
                    depth=0,
                    crawl_session_id=crawl_session_id
                )

                # ✅ CRITICAL: Check if parent creation succeeded before processing children
                if not sitemap_record_id:
                    logger.error(f"❌ Failed to create sitemap parent record for {url}")
                    return {
                        "success": False,
                        "error": "Failed to create sitemap parent record in database"
                    }

                logger.info(f"✅ Sitemap parent record created: {url} (id={sitemap_record_id})")

                # Step 2: Scrape and process all URLs with INTERLEAVED uploads
                logger.info(f"📤 Starting INTERLEAVED scraping, uploading, and recording for {len(urls_to_scrape)} URLs...")
                result = await self._scrape_urls_from_sitemap(
                    urls_to_scrape,
                    timeout=timeout,
                    max_concurrent=max_concurrent,
                    delay_between_requests=delay_between_requests,
                    sitemap_url=url,
                    celery_task_id=celery_task_id,
                    options=options,
                    sitemap_record_id=sitemap_record_id,
                    crawl_session_id=crawl_session_id,
                    max_pages=max_pages,
                    max_depth=max_depth,
                    include_patterns=include_patterns,
                    exclude_patterns=exclude_patterns
                )

            except Exception as e:
                logger.error(f"❌ Error processing sitemap: {e}")
                return {
                    "success": False,
                    "error": f"Failed to process sitemap: {str(e)}"
                }
        else:
            # Perform regular website scraping
            try:
                if CRAWL4AI_AVAILABLE:
                    result = await self._scrape_with_crawl4ai(
                        url, max_pages, max_depth, timeout,
                        delay_between_requests, max_concurrent,
                        include_patterns, exclude_patterns, url_type
                    )
                else:
                    return {
                        "success": False,
                        "error": "Crawl4AI is required for website scraping. Please install crawl4ai."
                    }
            except Exception as e:
                logger.error(f"❌ Error scraping website: {e}")
                return {
                    "success": False,
                    "error": str(e)
                }

        # Handle result from either sitemap or regular scraping
        if not result["success"]:
            return result

        # Try to process with Docling (convert HTML to markdown)
        # This is plug-and-play: if disabled or fails, falls back to raw content
        content_for_upload = result["content"]
        docling_metadata = {}

        if await should_use_docling_for_website():
            try:
                logger.info(f"🌐 Attempting docling conversion for {url}")
                markdown_content, docling_metadata = await process_html_with_docling(
                    result["content"],
                    url
                )

                if markdown_content:
                    # Successfully converted to markdown
                    content_for_upload = markdown_content
                    logger.info(
                        f"✅ Converted to markdown: {len(markdown_content)} chars"
                    )
                    # Print first 500 chars of markdown content for debugging
                    preview = markdown_content[:500] + ("..." if len(markdown_content) > 500 else "")
                    logger.info(f"📄 Markdown content preview:\n{preview}")
                else:
                    # Docling processing failed
                    if settings.docling_website_fallback_to_raw:
                        logger.info(f"⚠️ Docling failed for {url} - falling back to raw HTML")
                    else:
                        error_msg = docling_metadata.get("error", "Docling processing failed")
                        logger.error(f"❌ Docling processing failed and fallback disabled: {error_msg}")
                        return {
                            "success": False,
                            "error": error_msg,
                            "url": url
                        }

            except asyncio.TimeoutError:
                logger.warning(
                    f"⚠️ Docling timeout for {url} - falling back to raw HTML"
                )
            except Exception as e:
                # Supported file types for docling processing
                SUPPORTED_FILE_TYPES = {
                    ".pdf", ".docx", ".doc", ".pptx", ".ppt",
                    ".xlsx", ".xls", ".html", ".htm"
                }
                logger.warning(f"⚠️ Docling processing error for {url}: {e} - falling back to raw")

        from website_crawling.service.ai_service import upload_content_to_gemini, record_scraped_metadata

        # Check if interleaved mode was used (all uploading/recording already done)
        if result.get("interleaved_mode"):
            logger.info(f"✅ Sitemap processed in INTERLEAVED mode - {len(result.get('record_ids', []))} pages uploaded and recorded")
            processing_time = time.perf_counter() - start_time
            return {
                "success": result.get("success", False),
                "job_id": f"job_{int(time.time())}",
                "url": url,
                "status": "completed",
                "pages_scraped": len(result.get("record_ids", [])),
                "content_length": len(result.get("content", "")),
                "title": result.get("title"),
                "uploaded_files": result.get("uploaded_files", []),
                "record_ids": result.get("record_ids", []),
                "processing_time_seconds": round(processing_time, 2),
                "scraped_urls": result.get("scraped_urls", [url]),
                "mode": "interleaved"
            }

        # Check if this is a sitemap with individual pages to upload
        scraped_data = result.get("scraped_data", [])
        logger.info(f"🔍 [DEBUG] scraped_data from result: {len(scraped_data) if scraped_data else 0} pages available")

        if scraped_data and not result.get("interleaved_mode"):
            # Sitemap: Upload each page separately with its own URL
            logger.info(f"📋 Sitemap detected: uploading {len(scraped_data)} pages individually")

            # Generate unique session ID for this scraping session
            crawl_session_id = str(uuid.uuid4())
            logger.info(f"📊 Crawl session ID: {crawl_session_id}")

            uploaded_files = []
            record_ids = []
            url_to_record_id = {}  # Track URLs to their record IDs for parent linking

            # Create sitemap record first (depth=0, parent=None)
            sitemap_record_id = await record_scraped_metadata(
                url=url,  # The sitemap URL itself
                domain=urlparse(url).netloc.replace('www.', ''),
                title=result.get("title", url),
                content_length=len(result["content"]),
                pages_scraped=len(scraped_data),
                gemini_file_name=None,
                gemini_file_uri=None,
                gemini_state="DISCOVERED",
                scraped_urls=[url],
                scraping_config={
                    "max_pages": max_pages,
                    "max_depth": max_depth,
                    "source": "sitemap",
                    "include_patterns": include_patterns,
                    "exclude_patterns": exclude_patterns
                },
                file_search_metadata=None,
                parent_id=None,  # Sitemap is root
                depth=0,  # Sitemap is depth 0
                crawl_session_id=crawl_session_id
            )
            url_to_record_id[url] = sitemap_record_id
            logger.info(f"✅ Created sitemap parent record: {url} (depth=0, id={sitemap_record_id})")

            for page_idx, page_data in enumerate(scraped_data, 1):
                # ✅ CHECK FOR CANCELLATION AT START OF EACH PAGE
                if await self._check_cancellation(celery_task_id):
                    logger.warning(f"❌ [CANCEL] Task cancelled - stopping sitemap upload at page {page_idx}/{len(scraped_data)}")
                    break

                page_url = page_data["url"]
                page_text = page_data["text"]
                page_domain = urlparse(page_url).netloc.replace('www.', '')

                # Extract page title from first line or use domain
                page_title = ""
                if page_text:
                    first_line = page_text.split('\n')[0][:100]
                    page_title = first_line if first_line else page_domain

                logger.info(f"📄 [{page_idx}/{len(scraped_data)}] Uploading sitemap page: {page_url}")

                try:
                    # Upload individual page
                    gemini_result = await upload_content_to_gemini(
                        content=page_text,
                        url=page_url,  # Use individual page URL
                        title=page_title,
                        user_email=options.get("user_email"),
                        page_depth=1  # All sitemap URLs are depth 1 (direct children of sitemap)
                    )

                    # ✅ CHECK FOR CANCELLATION AFTER PAGE UPLOAD
                    if await self._check_cancellation(celery_task_id):
                        logger.warning(f"❌ [CANCEL] Task cancelled after page upload: {page_url}")
                        break

                    # All sitemap URLs have the sitemap.xml as parent (depth 1)
                    parent_id = sitemap_record_id

                    # Record metadata for individual page
                    logger.info(f"💾 Recording metadata for page {page_idx}/{len(scraped_data)}: {page_url}")

                    # Get celery_task_id for this page's metadata (same task for all pages in sitemap)
                    page_celery_task_id = celery_task_id if page_idx == 1 else None
                    logger.info(f"🆔 Page {page_idx} - Celery Task ID: {page_celery_task_id}")

                    record_id = await record_scraped_metadata(
                        url=page_url,  # Individual page URL in database
                        domain=page_domain,
                        title=page_title or page_url,
                        content_length=len(page_text),
                        pages_scraped=1,
                        gemini_file_name=gemini_result.get("file_name"),
                        gemini_file_uri=gemini_result.get("file_uri"),
                        gemini_state=gemini_result.get("state", "UNKNOWN"),
                        scraped_urls=[page_url],
                        scraping_config={
                            "max_pages": max_pages,
                            "max_depth": max_depth,
                            "source": "sitemap",
                            "sitemap_url": url,  # Store original sitemap URL
                            "include_patterns": include_patterns,
                            "exclude_patterns": exclude_patterns
                        },
                        file_search_metadata=gemini_result.get("file_search_metadata"),
                        parent_id=parent_id,  # Sitemap XML as parent
                        depth=1,  # All sitemap URLs are depth 1
                        crawl_session_id=crawl_session_id,
                        celery_task_id=page_celery_task_id  # Store task ID for each page
                    )

                    if record_id:
                        logger.info(f"✅ Recorded page {page_idx}/{len(scraped_data)} to database with ID: {record_id}")
                    else:
                        logger.error(f"❌ Failed to record page {page_idx}/{len(scraped_data)}: record_id is None")

                    uploaded_files.append({
                        "url": page_url,
                        "file_name": gemini_result.get("file_name"),
                        "record_id": record_id
                    })
                    record_ids.append(record_id)
                    url_to_record_id[page_url] = record_id

                except Exception as e:
                    logger.error(f"❌ Failed to upload/record page {page_idx}/{len(scraped_data)} ({page_url}): {e}")
                    import traceback
                    logger.error(f"Traceback: {traceback.format_exc()}")

            processing_time = time.perf_counter() - start_time

            logger.info(f"✅ Uploaded {len(uploaded_files)}/{len(scraped_data)} pages from sitemap")

            return {
                "success": True,
                "job_id": f"job_{int(time.time())}",
                "url": url,
                "status": "completed",
                "pages_scraped": len(uploaded_files),
                "content_length": len(result["content"]),
                "title": result.get("title"),
                "uploaded_files": uploaded_files,
                "record_ids": record_ids,
                "processing_time_seconds": round(processing_time, 2),
                "scraped_urls": result.get("scraped_urls", [url])
            }

        else:
            # Regular (non-sitemap) crawl: check if multi-page
            scraped_data = result.get("scraped_data", [])

            if scraped_data and len(scraped_data) > 1:
                # Multi-page crawl: upload each page individually with its own URL
                logger.info(f"📋 Regular multi-page crawl detected: uploading {len(scraped_data)} pages individually")

                # Generate unique session ID for this scraping session
                crawl_session_id = str(uuid.uuid4())
                logger.info(f"📊 Crawl session ID: {crawl_session_id}")

                uploaded_files = []
                record_ids = []
                all_child_urls = []
                url_to_record_id = {}  # Track URLs to their record IDs for parent linking

                # First, create the root URL as parent (depth=0) if it's in the scraped data
                root_page = next((page for page in scraped_data if page.get("depth", 0) == 0), None)
                root_record_id = None

                if root_page:
                    root_url = root_page["url"]
                    root_text = root_page["text"]
                    root_title = root_page.get("title", "")

                    logger.info(f"📄 Creating root page record: {root_url}")

                    try:
                        # Upload root page
                        gemini_result = await upload_content_to_gemini(
                            content=root_text,
                            url=root_url,
                            title=root_title,
                            user_email=options.get("user_email"),
                            page_depth=0
                        )

                        # ✅ CHECK FOR CANCELLATION AFTER ROOT PAGE UPLOAD
                        if await self._check_cancellation(celery_task_id):
                            logger.warning(f"❌ [CANCEL] Task cancelled after root page upload: {root_url}")
                            return {
                                "success": False,
                                "error": "Task cancelled by admin during upload"
                            }

                        # Record root page metadata
                        root_record_id = await record_scraped_metadata(
                            url=root_url,
                            domain=urlparse(root_url).netloc.replace('www.', ''),
                            title=root_title or root_url,
                            content_length=len(root_text),
                            pages_scraped=1,
                            gemini_file_name=gemini_result.get("file_name"),
                            gemini_file_uri=gemini_result.get("file_uri"),
                            gemini_state=gemini_result.get("state", "UNKNOWN"),
                            scraped_urls=[root_url],
                            scraping_config={
                                "max_pages": max_pages,
                                "max_depth": max_depth,
                                "page_depth": 0,
                                "source": "regular_crawl",
                                "parent_domain": urlparse(url).netloc,
                                "total_pages_in_crawl": len(scraped_data),
                                "include_patterns": include_patterns,
                                "exclude_patterns": exclude_patterns
                            },
                            file_search_metadata=gemini_result.get("file_search_metadata"),
                            parent_id=None,  # Root has no parent
                            depth=0,
                            crawl_session_id=crawl_session_id
                        )

                        uploaded_files.append({
                            "url": root_url,
                            "file_name": gemini_result.get("file_name"),
                            "record_id": root_record_id,
                            "depth": 0
                        })
                        record_ids.append(root_record_id)
                        url_to_record_id[root_url] = root_record_id
                        logger.info(f"✅ Created root page record: {root_url} (id={root_record_id})")
                    except Exception as e:
                        logger.error(f"❌ Failed to create root page record: {e}")

                # ✅ INTERLEAVED: Process all child pages (depth > 0)
                logger.info(f"📤 Processing {len(scraped_data) - 1} child pages with INTERLEAVED uploads...")
                for page_idx, page_data in enumerate(scraped_data, 1):
                    if page_idx == 1 and page_data.get("depth", 0) == 0:
                        # Skip root page - already processed above
                        continue

                    # ✅ CHECK FOR CANCELLATION
                    if await self._check_cancellation(celery_task_id):
                        logger.warning(f"❌ [CANCEL] Task cancelled during multi-page upload at page {page_idx}/{len(scraped_data)}")
                        break

                    page_url = page_data.get("url")
                    page_text = page_data.get("text", "")
                    page_depth = page_data.get("depth", 1)

                    if not page_url:
                        continue

                    logger.info(f"📤 [INTERLEAVED] Uploading child page {page_idx}/{len(scraped_data)}: {page_url}")

                    try:
                        # Upload child page
                        child_gemini_result = await upload_content_to_gemini(
                            content=page_text,
                            url=page_url,
                            title=page_data.get("title", page_url),
                            user_email=options.get("user_email"),
                            page_depth=page_depth
                        )

                        # ✅ CHECK FOR CANCELLATION AFTER CHILD PAGE UPLOAD
                        if await self._check_cancellation(celery_task_id):
                            logger.warning(f"❌ [CANCEL] Task cancelled after child page upload: {page_url}")
                            break

                        # Record child page immediately
                        logger.info(f"💾 [INTERLEAVED] Recording child page {page_idx}/{len(scraped_data)}: {page_url}")

                        child_record_id = await record_scraped_metadata(
                            url=page_url,
                            domain=urlparse(page_url).netloc.replace('www.', ''),
                            title=page_data.get("title", page_url),
                            content_length=len(page_text),
                            pages_scraped=1,
                            gemini_file_name=child_gemini_result.get("file_name"),
                            gemini_file_uri=child_gemini_result.get("file_uri"),
                            gemini_state=child_gemini_result.get("state", "UNKNOWN"),
                            scraped_urls=[page_url],
                            scraping_config={
                                "max_pages": max_pages,
                                "max_depth": max_depth,
                                "source": "regular_crawl",
                                "parent_domain": urlparse(url).netloc,
                                "include_patterns": include_patterns,
                                "exclude_patterns": exclude_patterns
                            },
                            file_search_metadata=child_gemini_result.get("file_search_metadata"),
                            parent_id=root_record_id,  # Link to root page
                            depth=page_depth,
                            crawl_session_id=crawl_session_id
                        )

                        if child_record_id:
                            logger.info(f"✅ [INTERLEAVED] Child page {page_idx} uploaded and recorded: {child_record_id}")
                            uploaded_files.append({
                                "url": page_url,
                                "file_name": child_gemini_result.get("file_name"),
                                "record_id": child_record_id,
                                "depth": page_depth
                            })
                            record_ids.append(child_record_id)
                            url_to_record_id[page_url] = child_record_id
                        else:
                            logger.error(f"❌ [INTERLEAVED] Failed to record child page {page_idx}: {page_url}")

                    except Exception as e:
                        logger.error(f"❌ [INTERLEAVED] Failed to upload/record child page {page_idx} ({page_url}): {e}")

                processing_time = time.perf_counter() - start_time

                return {
                    "success": True,
                    "job_id": f"job_{int(time.time())}",
                    "url": url,  # Original domain
                    "status": "completed",
                    "pages_scraped": len(uploaded_files),
                    "content_length": len(result["content"]),
                    "title": result.get("title"),
                    "uploaded_files": uploaded_files,
                    "record_ids": record_ids,
                    "processing_time_seconds": round(processing_time, 2),
                    "scraped_urls": all_child_urls,
                    "parent_domain": urlparse(url).netloc,
                    "mode": "interleaved"
                }
            else:
                # Single page or multi-URL crawl
                domain = urlparse(url).netloc.replace('www.', '')
                title = result.get("title") or ""  # Empty string if no title found (URL is already shown)
                discovered_urls = result.get("scraped_urls", [url])

                # Check if multiple child URLs were discovered
                if discovered_urls and len(discovered_urls) > 1:
                    # Multiple URLs discovered: create individual records for each
                    logger.info(f"📋 Single page has {len(discovered_urls)} child URLs - creating individual records")

                    crawl_session_id = str(uuid.uuid4())
                    logger.info(f"📊 Crawl session ID: {crawl_session_id}")

                    uploaded_files = []
                    record_ids = []
                    url_to_record_id = {}

                    # Upload parent URL first
                    gemini_result = await upload_content_to_gemini(
                        content=content_for_upload,
                        url=url,
                        title=title,
                        user_email=options.get("user_email"),
                        page_depth=0
                    )

                    # ✅ CHECK FOR CANCELLATION AFTER PARENT UPLOAD
                    if await self._check_cancellation(celery_task_id):
                        logger.warning(f"❌ [CANCEL] Task cancelled after parent URL upload: {url}")
                        return {
                            "success": False,
                            "error": "Task cancelled by admin during upload"
                        }

                    # Record parent
                    record_id = await record_scraped_metadata(
                        url=url,
                        domain=domain,
                        title=title,
                        content_length=len(result["content"]),
                        pages_scraped=1,
                        gemini_file_name=gemini_result.get("file_name"),
                        gemini_file_uri=gemini_result.get("file_uri"),
                        gemini_state=gemini_result.get("state", "UNKNOWN"),
                        scraped_urls=[url],
                        scraping_config={
                            "max_pages": max_pages,
                            "max_depth": max_depth,
                            "include_patterns": include_patterns,
                            "exclude_patterns": exclude_patterns
                        },
                        file_search_metadata=gemini_result.get("file_search_metadata"),
                        parent_id=None,
                        depth=0,
                        crawl_session_id=crawl_session_id
                    )

                    uploaded_files.append({
                        "url": url,
                        "file_name": gemini_result.get("file_name"),
                        "record_id": record_id,
                        "depth": 0
                    })
                    record_ids.append(record_id)
                    url_to_record_id[url] = record_id

                    # Record child URLs discovered during crawl
                    logger.info(f"📝 Recording {len(discovered_urls) - 1} child URLs discovered during crawl")
                    for child_url in discovered_urls:
                        # ✅ CHECK FOR CANCELLATION BEFORE RECORDING EACH CHILD
                        if await self._check_cancellation(celery_task_id):
                            logger.warning(f"❌ [CANCEL] Task cancelled - stopping child URL recording")
                            break

                        if child_url == url:
                            # Skip if it's the parent URL
                            continue

                        try:
                            logger.info(f"📄 Recording child URL: {child_url}")

                            # Record metadata for discovered child URL
                            child_record_id = await record_scraped_metadata(
                                url=child_url,
                                domain=urlparse(child_url).netloc.replace('www.', ''),
                                title=child_url,
                                content_length=0,  # Not actually scraped yet, just discovered
                                pages_scraped=0,
                                gemini_file_name=None,
                                gemini_file_uri=None,
                                gemini_state="DISCOVERED",
                                scraped_urls=[child_url],
                                scraping_config={
                                    "max_pages": max_pages,
                                    "max_depth": max_depth,
                                    "source": "discovered_during_crawl",
                                    "include_patterns": include_patterns,
                                    "exclude_patterns": exclude_patterns
                                },
                                file_search_metadata=None,
                                parent_id=record_id,  # Link to parent
                                depth=1,
                                crawl_session_id=crawl_session_id
                            )

                            record_ids.append(child_record_id)
                            url_to_record_id[child_url] = child_record_id
                            logger.info(f"✅ Recorded child URL: {child_url}")
                        except Exception as e:
                            logger.error(f"❌ Failed to record child URL {child_url}: {e}")

                    processing_time = time.perf_counter() - start_time

                    return {
                        "success": True,
                        "job_id": f"job_{int(time.time())}",
                        "url": url,
                        "status": "completed",
                        "pages_scraped": len(discovered_urls),
                        "pages_recorded": len(record_ids),
                        "content_length": len(result["content"]),
                        "title": title,
                        "gemini_file": gemini_result.get("file_name"),
                        "gemini_state": gemini_result.get("state"),
                        "record_ids": record_ids,
                        "processing_time_seconds": round(processing_time, 2),
                        "scraped_urls": discovered_urls,
                        "mode": "interleaved"
                    }

                else:
                    # True single page - only parent URL
                    gemini_result = await upload_content_to_gemini(
                        content=content_for_upload,
                        url=url,
                        title=title,
                        user_email=options.get("user_email"),
                        page_depth=0  # Single page has depth 0
                    )

                    # ✅ CHECK FOR CANCELLATION AFTER SINGLE PAGE UPLOAD
                    if await self._check_cancellation(celery_task_id):
                        logger.warning(f"❌ [CANCEL] Task cancelled after single page upload: {url}")
                        return {
                            "success": False,
                            "error": "Task cancelled by admin during upload"
                        }

                    # Record metadata to database
                    record_id = await record_scraped_metadata(
                        url=url,
                        domain=domain,
                        title=title,
                        content_length=len(result["content"]),
                        pages_scraped=result.get("pages_scraped", 1),
                        gemini_file_name=gemini_result.get("file_name"),
                        gemini_file_uri=gemini_result.get("file_uri"),
                        gemini_state=gemini_result.get("state", "UNKNOWN"),
                        scraped_urls=[url],
                        scraping_config={
                            "max_pages": max_pages,
                            "max_depth": max_depth,
                            "include_patterns": include_patterns,
                            "exclude_patterns": exclude_patterns
                        },
                        file_search_metadata=gemini_result.get("file_search_metadata"),
                        parent_id=None,
                        depth=0,
                        crawl_session_id=None
                    )

                    processing_time = time.perf_counter() - start_time

                    return {
                        "success": True,
                        "job_id": f"job_{int(time.time())}",
                        "url": url,
                        "status": "completed",
                        "pages_scraped": result.get("pages_scraped", 1),
                        "content_length": len(result["content"]),
                        "title": result.get("title"),
                        "gemini_file": gemini_result.get("file_name"),
                        "gemini_state": gemini_result.get("state"),
                        "record_id": record_id,
                        "processing_time_seconds": round(processing_time, 2),
                        "scraped_urls": [url],
                        "mode": "single_page"
                    }

    @staticmethod
    def calculate_url_depth(url: str) -> int:
        """
        Calculate depth of a URL based on path segments using BFS strategy.

        Examples:
            https://example.com -> 0 (root)
            https://example.com/about -> 1
            https://example.com/about/team -> 2
            https://example.com/about/team/members -> 3

        Args:
            url: The URL to calculate depth for

        Returns:
            Depth level (0 for root, 1+ for nested paths)
        """
        try:
            parsed = urlparse(url)
            # Count non-empty path segments
            path_parts = [p for p in parsed.path.split('/') if p]
            return len(path_parts)
        except Exception as e:
            logger.warning(f"⚠️ Error calculating URL depth for {url}: {e}")
            return 0

    async def _scrape_urls_from_sitemap(
        self,
        urls: List[str],
        timeout: int = 60,  # Increased from 30 to 60 seconds for better reliability
        max_concurrent: int = 10,
        delay_between_requests: float = 0,
        sitemap_url: str = None,
        celery_task_id: str = None,
        options: Dict[str, Any] = None,
        sitemap_record_id: int = None,
        crawl_session_id: str = None,
        max_pages: int = 1,
        max_depth: int = 2,
        include_patterns: List[str] = None,
        exclude_patterns: List[str] = None
    ) -> Dict[str, Any]:
        """
        Scrape all URLs from a sitemap with INTERLEAVED uploading and recording.
        Processes each page immediately after scraping: Scrape → Upload → Record → Next

        Args:
            urls: List of URLs to scrape from sitemap
            timeout: Request timeout in seconds
            max_concurrent: Maximum concurrent requests
            delay_between_requests: Delay between requests in seconds
            sitemap_url: The sitemap URL (will be the parent, depth=0)
            celery_task_id: Task ID for cancellation checking
            options: Scraping options
            sitemap_record_id: Database ID of sitemap parent record
            crawl_session_id: Session ID for grouping all pages from this crawl
            max_pages, max_depth: Crawl options
            include_patterns, exclude_patterns: URL targeting patterns

        Returns:
            Dict with summary of uploaded/recorded pages
        """
        from website_crawling.service.ai_service import upload_content_to_gemini, record_scraped_metadata

        scraped_data = []
        uploaded_files = []
        record_ids = []
        scraped_urls: Set[str] = set()
        title = "Sitemap Content"
        semaphore = asyncio.Semaphore(max_concurrent)

        options = options or {}
        include_patterns = include_patterns or []
        exclude_patterns = exclude_patterns or []

        # ✅ CRITICAL: Validate that sitemap parent record exists before processing children
        if not sitemap_record_id:
            logger.error("❌ Sitemap parent record ID is missing - cannot process child pages")
            return {
                "success": False,
                "error": "Sitemap parent record ID is missing"
            }

        if not urls:
            return {
                "success": False,
                "error": "No URLs provided to scrape from sitemap"
            }

        try:
            # Sort URLs alphabetically for consistent ordering
            sorted_urls = sorted(urls)
            logger.info(f"🎯 Starting sitemap crawl of {len(sorted_urls)} URLs (sorted alphabetically)")
            logger.debug(f"   Sitemap parent: {sitemap_url}")
            logger.debug(f"   Alphabetical order sample: {sorted_urls[:5] if len(sorted_urls) > 5 else sorted_urls}")

            async with AsyncWebCrawler(
                verbose=False,
                headless=True,
                browser_type="chromium",
                user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            ) as crawler:
                idx = 0
                for url in sorted_urls:
                    if url in scraped_urls:
                        continue

                    idx += 1

                    # ✅ CHECK FOR CANCELLATION AT START OF EACH LOOP ITERATION
                    if await self._check_cancellation(celery_task_id):
                        logger.warning(f"❌ [CANCEL] Task cancelled at sitemap loop iteration {idx}/{len(sorted_urls)}")
                        break

                    # Depth will be determined by crawl4ai's native BFS discovery
                    logger.info(f"📄 [Sitemap {idx}/{len(sorted_urls)}] Scraping: {url}")

                    try:
                        # Apply concurrency limit
                        async with semaphore:
                            result = None

                            # Strategy 1: Try with networkidle (most complete)
                            try:
                                result = await asyncio.wait_for(
                                    crawler.arun(
                                        url=url,
                                        bypass_cache=True,
                                        wait_until='networkidle'
                                    ),
                                    timeout=timeout
                                )
                            except asyncio.TimeoutError:
                                # Strategy 2: Timeout occurred, try with faster domcontentloaded
                                logger.warning(f"⏱️ Timeout with networkidle for {url}, retrying with domcontentloaded")
                                try:
                                    result = await asyncio.wait_for(
                                        crawler.arun(
                                            url=url,
                                            bypass_cache=True,
                                            wait_until='domcontentloaded'  # Faster loading strategy
                                        ),
                                        timeout=timeout // 2  # Use half timeout for faster retry
                                    )
                                except asyncio.TimeoutError:
                                    logger.warning(f"⏱️ Timeout with domcontentloaded for {url}, skipping")
                                    raise  # Re-raise to be caught by outer except
                                except Exception as retry_error:
                                    logger.warning(f"⚠️ Fallback attempt failed for {url}: {retry_error}")
                                    raise  # Re-raise to be caught by outer except
                            except Exception as cookie_error:
                                if "Invalid cookie fields" in str(cookie_error):
                                    # Strategy 3: Cookie error, retry with different cache settings
                                    logger.warning(f"⚠️ Cookie error for {url}, retrying with bypass_cache=False")
                                    try:
                                        result = await asyncio.wait_for(
                                            crawler.arun(
                                                url=url,
                                                bypass_cache=False,
                                                wait_until='domcontentloaded'
                                            ),
                                            timeout=timeout
                                        )
                                    except asyncio.TimeoutError:
                                        logger.warning(f"⏱️ Timeout on cookie retry for {url}")
                                        raise  # Re-raise to be caught by outer except
                                    except Exception as retry_error:
                                        logger.warning(f"⚠️ Cookie retry failed for {url}: {retry_error}")
                                        raise  # Re-raise to be caught by outer except
                                else:
                                    raise

                            if result and result.success:
                                scraped_urls.add(url)

                                # Get content
                                content = result.markdown or result.cleaned_html or result.html or ""
                                if content:
                                    # Store individual page data for citations
                                    page_title = ""
                                    if len(scraped_urls) == 1 and hasattr(result, 'title') and result.title:
                                        title = result.title
                                        page_title = result.title

                                    # All URLs extracted from sitemap are depth=1
                                    # Parent is the sitemap URL itself (depth=0)
                                    depth = 1  # All sitemap URLs are children of sitemap
                                    parent_url = sitemap_url

                                    # Classify URL type based on crawl4ai depth
                                    url_type = self.classify_url_type(url, crawl4ai_depth=depth)

                                    page_data = {
                                        "url": url,
                                        "text": content,
                                        "title": page_title,
                                        "depth": depth,
                                        "url_type": url_type,
                                        "parent_url": parent_url  # Parent is the sitemap
                                    }

                                    scraped_data.append(page_data)
                                    logger.info(f"✓ Successfully scraped sitemap URL: {url} (size={len(content)} bytes)")

                                    # ✅ INTERLEAVED: Upload and record this page immediately
                                    try:
                                        # ✅ CHECK FOR CANCELLATION BEFORE UPLOAD
                                        if await self._check_cancellation(celery_task_id):
                                            logger.warning(f"❌ [CANCEL] Task cancelled during sitemap upload at URL: {url}")
                                            break

                                        logger.info(f"📤 [INTERLEAVED] Uploading sitemap page {idx}/{len(sorted_urls)}: {url}")

                                        # Upload to Gemini
                                        gemini_result = await upload_content_to_gemini(
                                            content=content,
                                            url=url,
                                            title=page_title,
                                            user_email=options.get("user_email"),
                                            page_depth=depth
                                        )

                                        # ✅ CHECK FOR CANCELLATION AFTER UPLOAD COMPLETES
                                        if await self._check_cancellation(celery_task_id):
                                            logger.warning(f"❌ [CANCEL] Task cancelled after sitemap upload at URL: {url}")
                                            break

                                        # Record immediately after upload
                                        logger.info(f"💾 [INTERLEAVED] Recording page {idx}/{len(sorted_urls)}: {url}")

                                        page_celery_task_id = celery_task_id if idx == 1 else None
                                        record_id = await record_scraped_metadata(
                                            url=url,
                                            domain=urlparse(url).netloc.replace('www.', ''),
                                            title=page_title or url,
                                            content_length=len(content),
                                            pages_scraped=1,
                                            gemini_file_name=gemini_result.get("file_name"),
                                            gemini_file_uri=gemini_result.get("file_uri"),
                                            gemini_state=gemini_result.get("state", "UNKNOWN"),
                                            scraped_urls=[url],
                                            scraping_config={
                                                "max_pages": max_pages,
                                                "max_depth": max_depth,
                                                "source": "sitemap",
                                                "sitemap_url": sitemap_url,
                                                "include_patterns": include_patterns,
                                                "exclude_patterns": exclude_patterns
                                            },
                                            file_search_metadata=gemini_result.get("file_search_metadata"),
                                            parent_id=sitemap_record_id,
                                            depth=depth,
                                            crawl_session_id=crawl_session_id,
                                            celery_task_id=page_celery_task_id
                                        )

                                        if record_id:
                                            logger.info(f"✅ [INTERLEAVED] Page {idx}/{len(sorted_urls)} uploaded and recorded: {record_id}")
                                            uploaded_files.append({
                                                "url": url,
                                                "file_name": gemini_result.get("file_name"),
                                                "record_id": record_id
                                            })
                                            record_ids.append(record_id)
                                        else:
                                            logger.error(f"❌ [INTERLEAVED] Failed to record page {idx}/{len(sorted_urls)}: {url}")

                                    except Exception as upload_error:
                                        logger.error(f"❌ [INTERLEAVED] Failed to upload/record page {idx}/{len(sorted_urls)} ({url}): {upload_error}")
                            else:
                                logger.warning(f"⚠️ Failed to scrape sitemap URL {url}: {result.error_message}")

                            # Apply delay between requests
                            if delay_between_requests > 0 and idx < len(sorted_urls):
                                await asyncio.sleep(delay_between_requests)

                    except asyncio.TimeoutError:
                        logger.warning(f"⏱️ Timeout scraping sitemap URL {url}")
                    except Exception as e:
                        logger.warning(f"⚠️ Error scraping sitemap URL {url}: {e}")

            # Combine content for display but preserve individual page data
            combined_content = "\n\n".join([
                item['text']
                for item in scraped_data
            ])

            # Clean content to remove navigation artifacts and search prompts
            combined_content = self.clean_content(combined_content)

            # Log scraping summary
            logger.info(f"📊 Sitemap scraping summary:")
            logger.info(f"  Sitemap parent (depth=0): {sitemap_url}")
            logger.info(f"  Total URLs scraped (depth=1): {len(scraped_urls)}")
            logger.info(f"  Alphabetical ordering: Applied")
            if scraped_data:
                # Show sample of URLs in alphabetical order
                sample_urls = scraped_data[:5]
                logger.info(f"  Sample URLs (alphabetical order, all depth=1):")
                for i, sample in enumerate(sample_urls, 1):
                    logger.info(f"    {i}. {sample['url']}")

            return {
                "success": len(scraped_urls) > 0,
                "content": combined_content,
                "title": title,
                "pages_scraped": len(scraped_urls),
                "scraped_urls": list(scraped_urls),
                "scraped_data": scraped_data,  # Return individual page data with depth and parent info
                "uploaded_files": uploaded_files,  # Already uploaded and recorded via INTERLEAVED processing
                "record_ids": record_ids,
                "interleaved_mode": True  # Flag indicating processing was interleaved
            }

        except Exception as e:
            logger.error(f"❌ Sitemap scraping error: {e}")
            return {
                "success": False,
                "error": f"Failed to scrape sitemap URLs: {str(e)}"
            }

    async def _scrape_with_crawl4ai(
        self,
        url: str,
        max_pages: int,
        max_depth: int,
        timeout: int,
        delay_between_requests: float = 0,
        max_concurrent: int = 10,
        include_patterns: List[str] = None,
        exclude_patterns: List[str] = None,
        url_type: str = "website"  # New parameter: "website", "single_page", or "sitemap"
    ) -> Dict[str, Any]:
        """
        Scrape website using crawl4ai library with BFS depth-based traversal.
        Uses breadth-first strategy to crawl pages level-by-level, establishing
        proper parent-child relationships based on link discovery order.
        
        For single_page URLs: crawl4ai determines actual depth relative to domain root,
        and the original single_page becomes parent for all its discovered children.
        """
        if not CRAWL4AI_AVAILABLE:
            return {
                "success": False,
                "error": "Crawl4AI is required for website scraping. Please install crawl4ai."
            }
        
        include_patterns = include_patterns or []
        exclude_patterns = exclude_patterns or []
        scraped_data = []  # Track individual page data for citations
        scraped_urls: Set[str] = set()
        
        # Create semaphore early for both depth discovery and crawling phases
        semaphore = asyncio.Semaphore(max_concurrent)

        try:
            title = "Untitled"
            adjusted_max_depth = max_depth  # Default to max_depth, will be adjusted for single_page

            # For single_page crawling, we need to discover the actual depth of the starting URL
            # by crawling from domain root first, then finding our target URL's depth
            if url_type == "single_page":
                # Extract domain root for BFS discovery
                from urllib.parse import urlparse
                parsed = urlparse(url)
                domain_root = f"{parsed.scheme}://{parsed.netloc}"

                logger.info(f"🔍 Single_page mode: discovering actual depth for {url} from domain root {domain_root}")

                # Create crawler instance for both depth discovery and crawling phases
                async with AsyncWebCrawler(
                    verbose=False,
                    headless=True,
                    browser_type="chromium",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ) as crawler:
                    # Start BFS from domain root to discover the actual depth of our target URL
                    discovery_urls = [(domain_root, 0)]  # BFS queue: (url, depth) - start from domain root
                    target_url_depth = None  # Will store actual depth of our single_page
                    target_url_found = False

                    # First phase: discover the actual depth of our target single_page
                    while discovery_urls and not target_url_found and len(scraped_urls) < max_pages:
                        # ✅ CHECK FOR CANCELLATION AT START OF DISCOVERY LOOP
                        if await self._check_cancellation(celery_task_id):
                            logger.warning(f"❌ [CANCEL] Task cancelled during discovery phase")
                            break

                        current_url, depth = discovery_urls.pop(0)

                        if current_url in scraped_urls:
                            continue

                        try:
                            # Apply concurrency limit
                            async with semaphore:
                                result = await asyncio.wait_for(
                                    crawler.arun(url=current_url),
                                    timeout=timeout
                                )

                            if result.success:
                                scraped_urls.add(current_url)

                                # Check if this is our target single_page URL
                                if current_url.rstrip('/') == url.rstrip('/'):
                                    target_url_depth = depth
                                    target_url_found = True
                                    logger.info(f"🎯 Found target single_page {url} at actual depth {depth}")
                                    break

                                # Extract links for further discovery (only if we haven't found target yet)
                                if depth < max_depth and len(scraped_urls) < max_pages:
                                    links = extract_links_from_result(result, current_url)
                                    for link in links:
                                        if not self.should_include_url(link, include_patterns, exclude_patterns):
                                            continue
                                        if link not in scraped_urls and (link, depth + 1) not in discovery_urls:
                                            discovery_urls.append((link, depth + 1))

                        except Exception as e:
                            logger.warning(f"⚠️ Error during depth discovery for {current_url}: {e}")
                            continue

                    if target_url_depth is None:
                        logger.error(f"❌ Could not determine depth for single_page {url}")
                        return {"success": False, "error": f"Could not find target URL {url} during depth discovery"}

                    # Second phase: crawl starting from our single_page with its actual depth
                    logger.info(f"🚀 Starting crawl from single_page {url} at discovered depth {target_url_depth}")
                    scraped_urls.clear()  # Reset for actual crawling
                    scraped_data = []  # Reset for actual crawling
                
                    # For single_page crawling, adjust max_depth to allow crawling from single_page starting point
                    # Total depth should be: single_page_depth + ui_max_depth
                    # This means crawler can go up to ui_max_depth levels deeper than the single_page
                    adjusted_max_depth = target_url_depth + max_depth
                    logger.info(f"📏 Single_page crawling: single_page_depth={target_url_depth}, ui_max_depth={max_depth}, total_max_depth={adjusted_max_depth}")

                    urls_to_scrape = [(url, target_url_depth)]  # Start from single_page at its actual depth

                    # Continue with the same crawler for the actual crawling phase
                    # (The rest of the method will use the same crawler instance)
            else:
                # Regular website crawling: start from provided URL at depth 0
                urls_to_scrape = [(url, 0)]  # BFS queue: (url, depth) - depth based on discovery order

            # Create crawler instance for the main crawling phase
            # (For single_page, we already have a crawler instance from depth discovery)
            if url_type != "single_page":
                async with AsyncWebCrawler(
                    verbose=False,
                    headless=True,
                    browser_type="chromium",
                    user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
                ) as crawler:
                    # BFS traversal: process all URLs at depth N before depth N+1
                    while urls_to_scrape and len(scraped_urls) < max_pages:
                        # ✅ CHECK FOR CANCELLATION AT START OF BFS LOOP
                        if await self._check_cancellation(celery_task_id):
                            logger.warning(f"❌ [CANCEL] Task cancelled during BFS traversal")
                            break

                        current_url, depth = urls_to_scrape.pop(0)

                        if current_url in scraped_urls:
                            continue

                        logger.info(f"📄 Scraping page {len(scraped_urls) + 1}/{max_pages}: {current_url} (depth={depth})")

                        try:
                            # Apply concurrency limit
                            async with semaphore:
                                try:
                                    result = await asyncio.wait_for(
                                        crawler.arun(url=current_url),
                                        timeout=timeout
                                    )
                                except Exception as cookie_error:
                                    if "Invalid cookie fields" in str(cookie_error):
                                        logger.warning(f"⚠️ Cookie error for {current_url}, retrying with different settings")
                                        # Retry with different settings to avoid cookie handling
                                        result = await asyncio.wait_for(
                                            crawler.arun(
                                                url=current_url,
                                                bypass_cache=False,
                                                wait_until='domcontentloaded'
                                            ),
                                            timeout=timeout
                                        )
                                    else:
                                        raise
    
                                if result.success:
                                    scraped_urls.add(current_url)
    
                                    # Get content
                                    content = result.markdown or result.cleaned_html or result.html or ""
                                    if content:
                                        # Store individual page data for citations
                                        page_title = ""
                                        if len(scraped_urls) == 1 and hasattr(result, 'title') and result.title:
                                            title = result.title
                                            page_title = result.title
    
                                        # Classify URL type based on crawl4ai depth
                                        url_type = self.classify_url_type(current_url, crawl4ai_depth=depth)
                                        
                                        scraped_data.append({
                                            "url": current_url,
                                            "text": content,
                                            "title": page_title,
                                            "depth": depth,
                                            "url_type": url_type
                                        })
                                        
                                        # IMMEDIATELY process this URL to Firestore and database
                                        try:
                                            logger.info(f"🚀 Immediately processing scraped URL: {current_url} (depth={depth})")
                                            
                                            # Upload individual page with its own URL
                                            gemini_result = await upload_content_to_gemini(
                                                content=content,
                                                url=current_url,  # Use individual page URL
                                                title=page_title,
                                                user_email=options.get("user_email"),
                                                page_depth=depth
                                            )

                                            # ✅ CHECK FOR CANCELLATION AFTER PAGE UPLOAD
                                            if await self._check_cancellation(celery_task_id):
                                                logger.warning(f"❌ [CANCEL] Task cancelled after BFS page upload: {current_url}")
                                                break

                                            # Determine parent relationship
                                            parent_id = None
                                            current_depth = depth
                                            current_url_for_parent = current_url
                                            
                                            # Special handling for single_page crawling
                                            if url_type == "single_page":
                                                # The original single_page is the URL passed to scrape_website()
                                                original_single_page = url  # The URL passed to scrape_website()
                                                
                                                if original_single_page in url_to_record_id:
                                                    parent_id = url_to_record_id[original_single_page]
                                                    logger.info(f"🔗 Page {current_url} (depth={depth}) linked to original single_page parent {original_single_page} (id={parent_id})")
                                                else:
                                                    # If this is the original single_page itself, no parent needed
                                                    if current_url.rstrip('/') == original_single_page.rstrip('/'):
                                                        logger.info(f"🔗 Page {current_url} (depth={depth}) is original single_page, no parent")
                                                    else:
                                                        logger.warning(f"⚠️ Original single_page {original_single_page} not found in url_to_record_id for non-original page")
                                            else:
                                                # Regular website crawling: walk up URL hierarchy
                                                while current_depth > 0:
                                                    parent_url = self.get_parent_url(current_url_for_parent)
                                                    if not parent_url:
                                                        break
                                                    
                                                    if parent_url in url_to_record_id:
                                                        parent_id = url_to_record_id[parent_url]
                                                        logger.info(f"🔗 Page {current_url} (depth={depth}) linked to parent {parent_url} (depth={current_depth - 1}, id={parent_id})")
                                                        break
                                                    else:
                                                        # Parent doesn't exist yet, try going up one more level
                                                        current_url_for_parent = parent_url
                                                        current_depth -= 1
                                            
                                            if parent_id is None and depth > 0:
                                                logger.warning(f"⚠️ Could not find parent for {current_url} at depth {depth} - will link to root or null")
                                            
                                            # Record metadata for individual page
                                            record_id = await record_scraped_metadata(
                                                url=current_url,  # Individual page URL in database
                                                domain=urlparse(current_url).netloc.replace('www.', ''),
                                                title=page_title or current_url,
                                                content_length=len(content),
                                                pages_scraped=1,  # Each is a separate record
                                                gemini_file_name=gemini_result.get("file_name"),
                                                gemini_file_uri=gemini_result.get("file_uri"),
                                                gemini_state=gemini_result.get("state", "UNKNOWN"),
                                                scraped_urls=[current_url],  # Individual page URL for citation
                                                scraping_config={
                                                    "max_pages": max_pages,
                                                    "max_depth": max_depth,
                                                    "page_depth": depth,
                                                    "source": "regular_crawl",
                                                    "parent_domain": urlparse(url).netloc,
                                                    "total_pages_in_crawl": len(scraped_data),
                                                    "include_patterns": include_patterns,
                                                    "exclude_patterns": exclude_patterns
                                                },
                                                file_search_metadata=gemini_result.get("file_search_metadata"),
                                                parent_id=parent_id,
                                                depth=depth,
                                                crawl_session_id=str(uuid.uuid4())  # Unique session for each URL
                                            )
                                            
                                            # Add to tracking collections
                                            uploaded_files.append({
                                                "url": current_url,
                                                "file_name": gemini_result.get("file_name"),
                                                "record_id": record_id,
                                                "depth": depth
                                            })
                                            record_ids.append(record_id)
                                            url_to_record_id[current_url] = record_id
                                            
                                            logger.info(f"✅ Immediately uploaded and recorded: {current_url} (id={record_id})")
                                            
                                        except Exception as e:
                                            logger.error(f"❌ Failed to immediately process {current_url}: {e}")
    
                                    # Extract links for further crawling
                                    # Use adjusted_max_depth for single_page crawling, original max_depth for regular crawling
                                    current_max_depth = adjusted_max_depth if url_type == "single_page" else max_depth
                                    if depth < current_max_depth and len(scraped_urls) < max_pages:
                                        links = extract_links_from_result(result, current_url)
                                        for link in links:
                                            # Check if URL should be included based on patterns
                                            if not self.should_include_url(link, include_patterns, exclude_patterns):
                                                continue
    
                                            if link not in scraped_urls and (link, depth + 1) not in urls_to_scrape:
                                                urls_to_scrape.append((link, depth + 1))
    
                                else:
                                    logger.warning(f"⚠️ Failed to scrape {current_url}: {result.error_message}")
    
                                # Apply delay between requests
                                if delay_between_requests > 0 and urls_to_scrape:
                                    logger.info(f"⏳ Waiting {delay_between_requests}s before next request")
                                    await asyncio.sleep(delay_between_requests)
    
                        except asyncio.TimeoutError:
                            logger.warning(f"⏱️ Timeout scraping {current_url}")
                        except Exception as e:
                            logger.warning(f"⚠️ Error scraping {current_url}: {e}")

            # Combine content for display but preserve individual page data
            combined_content = "\n\n".join([
                item['text']
                for item in scraped_data
            ])

            # Clean content to remove navigation artifacts and search prompts
            combined_content = self.clean_content(combined_content)

            return {
                "success": len(scraped_urls) > 0,
                "content": combined_content,
                "title": title,
                "pages_scraped": len(scraped_urls),
                "scraped_urls": list(scraped_urls),
                "scraped_data": scraped_data  # Return individual page data
            }

        except Exception as e:
            logger.error(f"❌ crawl4ai error: {e}")
            return {
                "success": False,
                "error": str(e)
            }


# =============================================================================
# CELERY-BASED ASYNC WEBSITE SCRAPING
# =============================================================================

async def scrape_website_celery(
    url: str,
    options: Dict[str, Any]
) -> Dict[str, Any]:
    """
    Celery-based async scraping - returns immediately after creating DB record with pending status.
    Actual processing is dispatched to Celery worker.
    """
    try:
        service = WebsiteService()

        # Check if URL already exists (only active records: pending/processing/completed)
        existing = await service.scraping_dao.get_existing_website(url)
        if existing and not options.get("replace_existing", False):
            # Check if it also exists in Gemini FileSearch by inspecting stored metadata
            where_exists = ["database"]
            try:
                import json
                meta = existing['metadata']
                if isinstance(meta, str):
                    meta = json.loads(meta)
                if meta and meta.get('file_search_metadata'):
                    where_exists.append("FileSearch")
            except Exception:
                pass

            logger.info(f"⚠️ [DUPLICATE] Website already exists in {', '.join(where_exists)}: {url}")
            return {
                "success": False,
                "duplicate": True,
                "error": f"URL already exists in {', '.join(where_exists)}. Delete it first or enable Replace Existing.",
                "where_exists": where_exists,
                "existing_record": dict(existing)
            }

        if existing and options.get("replace_existing", False):
            logger.info(f"🔄 Replacing existing website: {url}")
            await service.scraping_dao.delete_website_record(url)

        # Create initial DB record with processing_status='pending'
        from shared.db import get_db_connection
        from urllib.parse import urlparse

        website_record_id = None
        async with get_db_connection() as conn:
            website_record_id = await conn.fetchval(
                """INSERT INTO scraped_websites (original_url, domain, processing_status, created_at)
                   VALUES ($1, $2, $3, NOW()) RETURNING id""",
                url,
                urlparse(url).netloc.replace('www.', ''),
                "pending"
            )

        logger.info(f"✅ [CELERY] Created scraped_websites record ID {website_record_id} with status='pending'")

        # Dispatch Celery task for actual scraping
        from website_crawling.tasks import scrape_website_task
        from website_crawling.celery_app import celery_app

        logger.info(f"📤 [TASK_DISPATCH] Preparing to dispatch task for website ID {website_record_id}, URL: {url}")

        task = scrape_website_task.delay(
            website_id=website_record_id,
            url=url,
            options=options
        )

        logger.info(f"✅ [CELERY] Dispatched Celery task {task.id} for website ID {website_record_id}")
        logger.info(f"📊 [TASK_INFO] Task State: {task.state}, Routing: 'web_crawling' queue, Timeout: 2 hours")

        # Store the Celery task_id in database so we can revoke it later if needed
        from shared.db import get_db_connection
        async with get_db_connection() as conn:
            await conn.execute(
                "UPDATE scraped_websites SET celery_task_id = $1 WHERE id = $2",
                task.id, website_record_id
            )
        logger.info(f"💾 [TASK_TRACKING] Stored celery_task_id {task.id} in database for website {website_record_id}")

        # Return immediate response with pending status
        return {
            "success": True,
            "message": "Website scraping queued for processing",
            "website": {
                "id": str(website_record_id),
                "url": url,
                "processing_status": "pending",
                "created_at": datetime.utcnow().isoformat()
            },
            "task_id": task.id
        }

    except Exception as e:
        logger.error(f"❌ [CELERY] Error in scrape_website_celery: {e}")
        raise

