"""
Website Service Layer for Website Crawling
Provides business logic for website scraping and crawling operations with session management
"""
import asyncio
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
    def classify_url_type(url: str) -> str:
        """
        Intelligently classify a URL as sitemap, single page, or website.

        Args:
            url: URL to classify

        Returns:
            One of: 'sitemap', 'single_page', 'website'
        """
        url_lower = url.lower()

        # Check if it's a sitemap
        if url_lower.endswith('.xml') or 'sitemap' in url_lower:
            logger.debug(f"📋 Classified as sitemap: {url}")
            return 'sitemap'

        try:
            parsed = urlparse(url)
            path_parts = [p for p in parsed.path.split('/') if p]

            # If URL has no path (just domain) or simple path (1-2 segments), treat as website
            # If URL has deeper path, could be single page
            # For now, classify as website if path is shallow, single_page if deeper
            if len(path_parts) <= 1:
                logger.debug(f"🌐 Classified as website (root/shallow): {url}")
                return 'website'
            elif len(path_parts) > 3:
                logger.debug(f"📄 Classified as single page (deep path): {url}")
                return 'single_page'
            else:
                # 2-3 segments: treat as website for crawling
                logger.debug(f"🌐 Classified as website (moderate depth): {url}")
                return 'website'
        except Exception as e:
            logger.warning(f"⚠️ Error classifying URL {url}: {e}, defaulting to website")
            return 'website'

    async def scrape_website(self, url: str, options: Dict[str, Any]) -> Dict[str, Any]:
        """
        Scrape a website and optionally crawl linked pages.

        Args:
            url: The URL to scrape
            options: Scraping options including:
                - max_pages: Maximum number of pages to scrape (default 1)
                - max_depth: Maximum crawl depth (default 2)
                - replace_existing: Whether to replace existing records
                - extract_links: Whether to follow links (default True)
                - timeout: Request timeout in seconds (default 30)

        Returns:
            Dict with scraping results
        """
        start_time = time.perf_counter()
        max_pages = options.get("max_pages", 1)
        max_depth = options.get("max_depth", 2)
        replace_existing = options.get("replace_existing", False)
        delay_between_requests = options.get("delay_between_requests", 0)
        max_concurrent = options.get("max_concurrent", 10)
        timeout = options.get("timeout", 30)
        include_patterns = options.get("include_patterns", []) or []
        exclude_patterns = options.get("exclude_patterns", []) or []

        logger.info(f"🌐 Starting scrape for {url} - max_pages={max_pages}, max_depth={max_depth}, delay={delay_between_requests}s, concurrent={max_concurrent}")
        if include_patterns or exclude_patterns:
            logger.info(f"🎯 URL targeting - include: {len(include_patterns)} patterns, exclude: {len(exclude_patterns)} patterns")

        # Check for existing record
        existing = await self.scraping_dao.get_existing_website(url)
        if existing and not replace_existing:
            logger.info(f"⚠️ Website already exists: {url}")
            return {
                "success": False,
                "error": "Website already exists. Set replace_existing=true to update.",
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

                # Scrape all URLs from sitemap
                result = await self._scrape_urls_from_sitemap(
                    urls_to_scrape, timeout, max_concurrent, delay_between_requests
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
                        include_patterns, exclude_patterns
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

        # Check if this is a sitemap with individual pages to upload
        scraped_data = result.get("scraped_data", [])

        if scraped_data:
            # Sitemap: Upload each page separately with its own URL
            logger.info(f"📋 Sitemap detected: uploading {len(scraped_data)} pages individually")

            # Generate unique session ID for this scraping session
            crawl_session_id = str(uuid.uuid4())
            logger.info(f"📊 Crawl session ID: {crawl_session_id}")

            uploaded_files = []
            record_ids = []
            url_to_record_id = {}  # Track URLs to their record IDs for parent linking

            for page_data in scraped_data:
                page_url = page_data["url"]
                page_text = page_data["text"]
                page_depth = page_data.get("depth", 0)
                page_domain = urlparse(page_url).netloc.replace('www.', '')

                # Extract page title from first line or use domain
                page_title = ""
                if page_text:
                    first_line = page_text.split('\n')[0][:100]
                    page_title = first_line if first_line else page_domain

                logger.info(f"📄 Uploading page: {page_url}")

                try:
                    # Upload individual page
                    gemini_result = await upload_content_to_gemini(
                        content=page_text,
                        url=page_url,  # Use individual page URL
                        title=page_title,
                        user_email=options.get("user_email"),
                        page_depth=page_depth  # Pass the calculated depth
                    )

                    # Determine parent relationship
                    parent_id = None
                    if page_depth > 0:
                        # Use parent_url from page_data if available (from BFS sitemap analysis)
                        parent_url = page_data.get("parent_url")

                        # If parent_url not in page_data, calculate it using path analysis
                        if not parent_url:
                            parent_url = self.get_parent_url(page_url)

                        if parent_url:
                            if parent_url in url_to_record_id:
                                # Parent already exists
                                parent_id = url_to_record_id[parent_url]
                                logger.info(f"🔗 Page {page_url} (depth={page_depth}) linked to existing parent {parent_url} (id={parent_id})")
                            else:
                                # Parent doesn't exist - create all missing parent levels up to root
                                logger.info(f"📝 Creating parent record hierarchy for {page_url}")

                                # Collect all missing parents in the chain from immediate parent to root
                                missing_parents = []
                                current_url = page_url
                                current_depth = page_depth

                                while current_url:
                                    current_url = self.get_parent_url(current_url)
                                    if not current_url:
                                        break
                                    current_depth -= 1

                                    # Check if this URL already has a record
                                    if current_url not in url_to_record_id:
                                        missing_parents.append((current_url, current_depth))
                                    else:
                                        # Found an existing parent - stop here
                                        logger.debug(f"  Found existing parent at depth {current_depth}: {current_url}")
                                        break

                                # Create all missing parents (in reverse order from root to immediate parent)
                                if missing_parents:
                                    for missing_url, missing_depth in reversed(missing_parents):
                                        if missing_url not in url_to_record_id:
                                            # Get the parent's parent (which might exist or need to be created)
                                            grandparent_url = self.get_parent_url(missing_url)
                                            grandparent_id = url_to_record_id.get(grandparent_url) if grandparent_url else None

                                            parent_record_id = await record_scraped_metadata(
                                                url=missing_url,
                                                domain=urlparse(missing_url).netloc.replace('www.', ''),
                                                title=missing_url,
                                                content_length=0,
                                                pages_scraped=0,
                                                gemini_file_name=None,
                                                gemini_file_uri=None,
                                                gemini_state="DISCOVERED",
                                                scraped_urls=[missing_url],
                                                scraping_config={
                                                    "max_pages": max_pages,
                                                    "max_depth": max_depth,
                                                    "source": "sitemap",
                                                    "sitemap_url": url,
                                                    "include_patterns": include_patterns,
                                                    "exclude_patterns": exclude_patterns
                                                },
                                                file_search_metadata=None,
                                                parent_id=grandparent_id,
                                                depth=missing_depth,
                                                crawl_session_id=crawl_session_id
                                            )
                                            url_to_record_id[missing_url] = parent_record_id
                                            logger.info(f"✅ Created parent record: {missing_url} (depth={missing_depth}, parent_id={grandparent_id})")

                                parent_id = url_to_record_id.get(parent_url)
                                if parent_id:
                                    logger.info(f"🔗 Page {page_url} (depth={page_depth}) linked to parent {parent_url} (id={parent_id})")
                                else:
                                    logger.warning(f"⚠️ Failed to establish parent for {page_url}: parent {parent_url} not in mapping")
                        else:
                            logger.warning(f"⚠️ Could not calculate parent for {page_url} at depth {page_depth}")
                    else:
                        # Root page - check if this URL was already processed as a parent
                        if page_url in url_to_record_id:
                            # This URL is already a parent, so don't create a new root record
                            logger.info(f"🔄 Skipping duplicate root page: {page_url}")
                            continue

                    # Record metadata for individual page
                    record_id = await record_scraped_metadata(
                        url=page_url,  # Individual page URL in database
                        domain=urlparse(page_url).netloc.replace('www.', ''),
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
                        parent_id=parent_id,
                        depth=page_depth,
                        crawl_session_id=crawl_session_id
                    )

                    uploaded_files.append({
                        "url": page_url,
                        "file_name": gemini_result.get("file_name"),
                        "record_id": record_id
                    })
                    record_ids.append(record_id)
                    url_to_record_id[page_url] = record_id

                except Exception as e:
                    logger.error(f"❌ Failed to upload page {page_url}: {e}")

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

                for page_data in scraped_data:
                    page_url = page_data["url"]
                    page_text = page_data["text"]
                    page_title = page_data.get("title", "")
                    page_depth = page_data.get("depth", 0)

                    all_child_urls.append(page_url)

                    try:
                        # Upload individual page with its own URL
                        gemini_result = await upload_content_to_gemini(
                            content=page_text,
                            url=page_url,  # Use individual page URL
                            title=page_title,
                            user_email=options.get("user_email"),
                            page_depth=page_depth  # Add missing page_depth parameter
                        )

                        # Determine parent relationship
                        parent_id = None
                        if page_depth > 0:
                            # Find parent URL by removing last path segment
                            parent_url = self.get_parent_url(page_url)
                            if parent_url and parent_url in url_to_record_id:
                                parent_id = url_to_record_id[parent_url]
                                logger.info(f"🔗 Page {page_url} linked to parent {parent_url} (id={parent_id})")
                            else:
                                logger.warning(f"⚠️ Could not find parent for {page_url} at depth {page_depth}")
                        else:
                            # Root page - check if this URL was already processed as a parent
                            if page_url in url_to_record_id:
                                # This URL is already a parent, so don't create a new root record
                                logger.info(f"🔄 Skipping duplicate root page: {page_url}")
                                continue

                        # Record metadata for individual page
                        record_id = await record_scraped_metadata(
                            url=page_url,  # Individual page URL in database
                            domain=urlparse(page_url).netloc.replace('www.', ''),
                            title=page_title or page_url,
                            content_length=len(page_text),
                            pages_scraped=1,  # Each is a separate record
                            gemini_file_name=gemini_result.get("file_name"),
                            gemini_file_uri=gemini_result.get("file_uri"),
                            gemini_state=gemini_result.get("state", "UNKNOWN"),
                            scraped_urls=[page_url],  # Individual page URL for citation
                            scraping_config={
                                "max_pages": max_pages,
                                "max_depth": max_depth,
                                "page_depth": page_depth,
                                "source": "regular_crawl",
                                "parent_domain": urlparse(url).netloc,
                                "total_pages_in_crawl": len(scraped_data),
                                "include_patterns": include_patterns,
                                "exclude_patterns": exclude_patterns
                            },
                            file_search_metadata=gemini_result.get("file_search_metadata"),
                            parent_id=parent_id,
                            depth=page_depth,
                            crawl_session_id=crawl_session_id
                        )

                        uploaded_files.append({
                            "url": page_url,
                            "file_name": gemini_result.get("file_name"),
                            "record_id": record_id,
                            "depth": page_depth
                        })
                        record_ids.append(record_id)
                        url_to_record_id[page_url] = record_id

                        logger.info(f"✅ Uploaded child page: {page_url}")

                    except Exception as e:
                        logger.error(f"❌ Failed to upload page {page_url}: {e}")

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
                    "parent_domain": urlparse(url).netloc
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
                        "scraped_urls": discovered_urls
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
                        "scraped_urls": [url]
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
        timeout: int = 30,
        max_concurrent: int = 10,
        delay_between_requests: float = 0
    ) -> Dict[str, Any]:
        """
        Scrape all URLs from a sitemap using BFS depth-based traversal.
        Uses breadth-first strategy to crawl pages level-by-level, establishing
        proper parent-child relationships based on URL structure.

        Args:
            urls: List of URLs to scrape from sitemap
            timeout: Request timeout in seconds
            max_concurrent: Maximum concurrent requests
            delay_between_requests: Delay between requests in seconds

        Returns:
            Dict with scraped content and metadata with proper hierarchy
        """
        scraped_data = []
        scraped_urls: Set[str] = set()
        url_depth_map = {}  # Track depth for each URL
        title = "Sitemap Content"
        semaphore = asyncio.Semaphore(max_concurrent)

        if not urls:
            return {
                "success": False,
                "error": "No URLs provided to scrape from sitemap"
            }

        try:
            # Use BFS queue: process URLs level-by-level by path depth
            # Group URLs by their path depth for proper BFS ordering
            bfs_queue = []
            depth_groups = {}

            for url in urls:
                # Calculate depth from URL path structure
                path_depth = self.calculate_url_depth(url)
                if path_depth not in depth_groups:
                    depth_groups[path_depth] = []
                depth_groups[path_depth].append(url)
                url_depth_map[url] = path_depth

            # Build BFS queue: process all depth-0 first, then depth-1, etc
            for depth in sorted(depth_groups.keys()):
                bfs_queue.extend([(url, depth) for url in depth_groups[depth]])

            logger.info(f"🎯 Starting BFS deep crawl of {len(urls)} sitemap URLs across {len(depth_groups)} depth levels")

            async with AsyncWebCrawler(verbose=False) as crawler:
                idx = 0
                for url, depth in bfs_queue:
                    if url in scraped_urls:
                        continue

                    idx += 1
                    logger.info(f"📄 [BFS {idx}/{len(urls)}] Scraping: {url} (depth={depth})")

                    try:
                        # Apply concurrency limit
                        async with semaphore:
                            result = await asyncio.wait_for(
                                crawler.arun(
                                    url=url,
                                    bypass_cache=True,
                                    wait_until='networkidle'
                                ),
                                timeout=timeout
                            )

                            if result.success:
                                scraped_urls.add(url)

                                # Get content
                                content = result.markdown or result.cleaned_html or result.html or ""
                                if content:
                                    # Store individual page data for citations
                                    page_title = ""
                                    if len(scraped_urls) == 1 and hasattr(result, 'title') and result.title:
                                        title = result.title
                                        page_title = result.title

                                    # Calculate parent URL for this page
                                    parent_url = None
                                    if depth > 0:
                                        parent_url = self.get_parent_url(url)
                                        logger.debug(f"🔗 Page {url} -> parent: {parent_url}")

                                    page_data = {
                                        "url": url,
                                        "text": content,
                                        "title": page_title,
                                        "depth": depth,
                                        "parent_url": parent_url
                                    }

                                    scraped_data.append(page_data)
                                    logger.info(f"✓ Successfully scraped: {url} (depth={depth}, size={len(content)} bytes)")
                            else:
                                logger.warning(f"⚠️ Failed to scrape sitemap URL {url}: {result.error_message}")

                            # Apply delay between requests
                            if delay_between_requests > 0 and idx < len(bfs_queue):
                                await asyncio.sleep(delay_between_requests)

                    except asyncio.TimeoutError:
                        logger.warning(f"⏱️ Timeout scraping sitemap URL {url} (depth={depth})")
                    except Exception as e:
                        logger.warning(f"⚠️ Error scraping sitemap URL {url}: {e}")

            # Combine content for display but preserve individual page data
            combined_content = "\n\n".join([
                item['text']
                for item in scraped_data
            ])

            # Clean content to remove navigation artifacts and search prompts
            combined_content = self.clean_content(combined_content)

            # Log hierarchy information with verification
            logger.info(f"📊 Sitemap hierarchy summary:")
            max_depth = max([s['depth'] for s in scraped_data] + [0])
            for depth_level in range(max_depth + 1):
                urls_at_depth = [s for s in scraped_data if s['depth'] == depth_level]
                if urls_at_depth:
                    logger.info(f"  Depth {depth_level}: {len(urls_at_depth)} URLs")
                    # Log a sample of URLs at this depth
                    sample_urls = urls_at_depth[:3]
                    for sample in sample_urls:
                        parent_info = f" (parent: {sample.get('parent_url', 'N/A')})" if sample.get('parent_url') else ""
                        logger.debug(f"    - {sample['url']}{parent_info}")

            return {
                "success": len(scraped_urls) > 0,
                "content": combined_content,
                "title": title,
                "pages_scraped": len(scraped_urls),
                "scraped_urls": list(scraped_urls),
                "scraped_data": scraped_data  # Return individual page data with depth and parent info
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
        exclude_patterns: List[str] = None
    ) -> Dict[str, Any]:
        """
        Scrape website using crawl4ai library with BFS depth-based traversal.
        Uses breadth-first strategy to crawl pages level-by-level, establishing
        proper parent-child relationships based on link discovery order.
        """
        include_patterns = include_patterns or []
        exclude_patterns = exclude_patterns or []
        scraped_data = []  # Track individual page data for citations
        scraped_urls: Set[str] = set()
        urls_to_scrape = [(url, 0)]  # BFS queue: (url, depth) - depth based on discovery order
        title = "Untitled"
        semaphore = asyncio.Semaphore(max_concurrent)

        try:
            async with AsyncWebCrawler(verbose=False) as crawler:
                # BFS traversal: process all URLs at depth N before depth N+1
                while urls_to_scrape and len(scraped_urls) < max_pages:
                    current_url, depth = urls_to_scrape.pop(0)

                    if current_url in scraped_urls:
                        continue

                    logger.info(f"📄 Scraping page {len(scraped_urls) + 1}/{max_pages}: {current_url} (depth={depth})")

                    try:
                        # Apply concurrency limit
                        async with semaphore:
                            result = await asyncio.wait_for(
                                crawler.arun(url=current_url),
                                timeout=timeout
                            )

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

                                    scraped_data.append({
                                        "url": current_url,
                                        "text": content,
                                        "title": page_title,
                                        "depth": depth
                                    })

                                # Extract links for further crawling
                                if depth < max_depth and len(scraped_urls) < max_pages:
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

