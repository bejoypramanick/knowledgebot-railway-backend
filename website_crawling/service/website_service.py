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

# Fallback imports for basic HTTP scraping
try:
    import httpx
    from bs4 import BeautifulSoup
    HTTPX_AVAILABLE = True
except ImportError:
    HTTPX_AVAILABLE = False


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
                elif HTTPX_AVAILABLE:
                    result = await self._scrape_with_httpx(
                        url, max_pages, max_depth, timeout,
                        delay_between_requests, max_concurrent,
                        include_patterns, exclude_patterns
                    )
                else:
                    return {
                        "success": False,
                        "error": "No scraping library available. Please install crawl4ai or httpx+beautifulsoup4."
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
                        url=page_url,  # Use child page URL, not sitemap URL
                        title=page_title,
                        user_email=options.get("user_email")
                    )

                    # Determine parent relationship
                    parent_id = None
                    # For sitemaps, pages are siblings (all children of the sitemap)
                    # We don't track hierarchical parent-child in sitemaps
                    depth = 0

                    # Record metadata for individual page
                    record_id = await record_scraped_metadata(
                        url=page_url,  # Use child page URL
                        domain=page_domain,
                        title=page_title,
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
                        depth=depth,
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
                            user_email=options.get("user_email")
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
                # Single page: Upload normally
                domain = urlparse(url).netloc.replace('www.', '')
                title = result.get("title") or ""  # Empty string if no title found (URL is already shown)

                gemini_result = await upload_content_to_gemini(
                    content=content_for_upload,
                    url=url,
                    title=title,
                    user_email=options.get("user_email")
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
                    scraped_urls=result.get("scraped_urls", [url]),
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
                    "scraped_urls": result.get("scraped_urls", [url])
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
        """Scrape using crawl4ai library with rate limiting support."""
        include_patterns = include_patterns or []
        exclude_patterns = exclude_patterns or []
        scraped_data = []  # Track individual page data for citations
        scraped_urls: Set[str] = set()
        urls_to_scrape = [(url, 0)]  # (url, depth)
        title = "Untitled"
        semaphore = asyncio.Semaphore(max_concurrent)

        try:
            async with AsyncWebCrawler(verbose=False) as crawler:
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
            combined_content = "\n".join([
                f"\n\n--- Page: {item['url']} ---\n\n{item['text']}"
                for item in scraped_data
            ])

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

    async def _scrape_with_httpx(
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
        """Fallback scraping using httpx and BeautifulSoup with rate limiting."""
        include_patterns = include_patterns or []
        exclude_patterns = exclude_patterns or []
        scraped_data = []  # Track individual page data for citations
        scraped_urls: Set[str] = set()
        urls_to_scrape = [(url, 0)]  # (url, depth)
        title = "Untitled"
        semaphore = asyncio.Semaphore(max_concurrent)

        headers = {
            "User-Agent": "KnowledgeBot-Crawler/1.0 (+https://globistaan.com)"
        }

        async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
            while urls_to_scrape and len(scraped_urls) < max_pages:
                current_url, depth = urls_to_scrape.pop(0)

                if current_url in scraped_urls:
                    continue

                logger.info(f"📄 Scraping page {len(scraped_urls) + 1}/{max_pages}: {current_url} (depth={depth})")

                try:
                    # Apply concurrency limit
                    async with semaphore:
                        response = await client.get(current_url, headers=headers)
                        response.raise_for_status()

                        scraped_urls.add(current_url)

                        # Parse HTML
                        soup = BeautifulSoup(response.text, 'lxml')

                        # Remove script and style elements
                        for element in soup(['script', 'style', 'nav', 'footer', 'header']):
                            element.decompose()

                        # Get title from first page
                        page_title = ""
                        if len(scraped_urls) == 1:
                            title_tag = soup.find('title')
                            if title_tag:
                                title = title_tag.get_text(strip=True)
                                page_title = title

                        # Extract text content
                        text = soup.get_text(separator='\n', strip=True)
                        # Clean up excessive whitespace
                        text = re.sub(r'\n{3,}', '\n\n', text)

                        if text:
                            # Store individual page data for citations
                            scraped_data.append({
                                "url": current_url,
                                "text": text,
                                "title": page_title,
                                "depth": depth
                            })

                        # Extract links for further crawling
                        if depth < max_depth and len(scraped_urls) < max_pages:
                            base_domain = urlparse(url).netloc
                            for link in soup.find_all('a', href=True):
                                href = link['href']
                                # Make absolute URL
                                absolute_url = urljoin(current_url, href)
                                parsed = urlparse(absolute_url)

                                # Only follow same-domain links
                                if parsed.netloc == base_domain:
                                    clean_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"

                                    # Check if URL should be included based on patterns
                                    if not self.should_include_url(clean_url, include_patterns, exclude_patterns):
                                        continue

                                    if clean_url not in scraped_urls:
                                        urls_to_scrape.append((clean_url, depth + 1))

                        # Apply delay between requests
                        if delay_between_requests > 0 and urls_to_scrape:
                            logger.info(f"⏳ Waiting {delay_between_requests}s before next request")
                            await asyncio.sleep(delay_between_requests)

                except httpx.HTTPStatusError as e:
                    logger.warning(f"⚠️ HTTP error scraping {current_url}: {e.response.status_code}")
                except Exception as e:
                    logger.warning(f"⚠️ Error scraping {current_url}: {e}")

        # Combine content for display but preserve individual page data
        combined_content = "\n".join([
            f"\n\n--- Page: {item['url']} ---\n\n{item['text']}"
            for item in scraped_data
        ])

        return {
            "success": len(scraped_urls) > 0,
            "content": combined_content,
            "title": title,
            "pages_scraped": len(scraped_urls),
            "scraped_urls": list(scraped_urls),
            "scraped_data": scraped_data  # Return individual page data
        }

    async def _scrape_urls_from_sitemap(
        self,
        urls: List[str],
        timeout: int,
        max_concurrent: int = 10,
        delay_between_requests: float = 0
    ) -> Dict[str, Any]:
        """Scrape multiple URLs from a sitemap in parallel."""
        all_content = []
        scraped_urls: Set[str] = set()
        title = "Sitemap Collection"
        scraped_data = []  # Store results with order preserved

        headers = {
            "User-Agent": "KnowledgeBot-Crawler/1.0 (+https://globistaan.com)"
        }

        try:
            import httpx
            from bs4 import BeautifulSoup

            # Limit concurrent requests to avoid overwhelming target site
            semaphore = asyncio.Semaphore(max_concurrent)

            async def scrape_single_url(url: str, index: int, client: httpx.AsyncClient):
                """Scrape a single URL with rate limiting."""
                async with semaphore:
                    logger.info(f"📄 Scraping URL {index+1}/{len(urls)}: {url}")

                    try:
                        response = await client.get(url, headers=headers)
                        response.raise_for_status()

                        # Parse HTML
                        soup = BeautifulSoup(response.text, 'lxml')

                        # Remove script and style elements
                        for element in soup(['script', 'style', 'nav', 'footer', 'header']):
                            element.decompose()

                        # Get title (will use from first page later)
                        page_title = None
                        if index == 0:
                            title_tag = soup.find('title')
                            if title_tag:
                                page_title = title_tag.get_text(strip=True)

                        # Extract text content
                        text = soup.get_text(separator='\n', strip=True)
                        text = re.sub(r'\n{3,}', '\n\n', text)

                        return {
                            "success": True,
                            "url": url,
                            "index": index,
                            "text": text,
                            "title": page_title
                        }

                    except httpx.HTTPStatusError as e:
                        logger.warning(f"⚠️ HTTP error scraping {url}: {e.response.status_code}")
                        return {"success": False, "url": url, "index": index, "error": str(e)}
                    except Exception as e:
                        logger.warning(f"⚠️ Error scraping {url}: {e}")
                        return {"success": False, "url": url, "index": index, "error": str(e)}

            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                # Scrape all URLs in parallel with semaphore limiting concurrency
                tasks = [scrape_single_url(url, i, client) for i, url in enumerate(urls)]
                results = await asyncio.gather(*tasks, return_exceptions=True)

                # Process results in original order
                for result in results:
                    if isinstance(result, Exception):
                        logger.error(f"Exception in parallel scraping: {result}")
                        continue

                    if result.get("success"):
                        scraped_urls.add(result["url"])

                        # Get title from first successful page
                        if result.get("title") and title == "Sitemap Collection":
                            title = result["title"]

                        # Append content in order
                        if result.get("text"):
                            scraped_data.append({
                                "index": result["index"],
                                "url": result["url"],
                                "text": result["text"]
                            })

                # Sort by original index to maintain URL order
                scraped_data.sort(key=lambda x: x["index"])

                # Combine content
                for item in scraped_data:
                    all_content.append(f"\n\n--- Page: {item['url']} ---\n\n{item['text']}")

            combined_content = "\n".join(all_content)

            return {
                "success": len(scraped_urls) > 0,
                "content": combined_content,
                "title": title,
                "pages_scraped": len(scraped_urls),
                "scraped_urls": list(scraped_urls),
                "scraped_data": scraped_data  # Include individual page data for separate uploads
            }

        except Exception as e:
            logger.error(f"❌ Error in sitemap scraping: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def get_all_jobs(self) -> List[Dict[str, Any]]:
        """Get all scraping jobs from database."""
        try:
            # Query database for all scraped websites
            from shared.db import get_db_connection
            query = """
                SELECT id, original_url as url, domain, title, description,
                       gemini_state, pages_scraped, content_length, created_at
                FROM scraped_websites
                ORDER BY created_at DESC
                LIMIT 100
            """
            async with get_db_connection() as conn:
                rows = await conn.fetch(query)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error getting all jobs: {e}")
            return []

    async def get_job_details(self, job_id: str) -> Optional[Dict[str, Any]]:
        """Get details of a specific scraping job."""
        try:
            from shared.db import get_db_connection
            query = """
                SELECT id, original_url as url, domain, title, description,
                       gemini_state, pages_scraped, content_length,
                       gemini_file_name, gemini_file_uri, gemini_state,
                       created_at, updated_at
                FROM scraped_websites
                WHERE id = $1
            """
            async with get_db_connection() as conn:
                row = await conn.fetchrow(query, int(job_id) if job_id.isdigit() else job_id)
                return dict(row) if row else None
        except Exception as e:
            logger.error(f"Error getting job details {job_id}: {e}")
            return None

    async def delete_website_hierarchy(self, job_id: str) -> Dict[str, Any]:
        """Delete a website and all its child pages from FileSearch first, then database."""
        try:
            from shared.db import get_db_connection
            from website_crawling.core.ai import get_genai_client

            # First get all records in the hierarchy (parent + all children)
            async with get_db_connection() as conn:
                # Get parent and all recursive children
                hierarchy_query = """
                    WITH RECURSIVE website_hierarchy AS (
                        -- Base case: the parent page
                        SELECT id, original_url, metadata, parent_id, depth, 0 as level
                        FROM scraped_websites 
                        WHERE id = $1
                        
                        UNION ALL
                        
                        -- Recursive case: all children
                        SELECT w.id, w.original_url, w.metadata, w.parent_id, w.depth, wh.level + 1
                        FROM scraped_websites w
                        INNER JOIN website_hierarchy wh ON w.parent_id = wh.id
                    )
                    SELECT id, original_url, metadata, level
                    FROM website_hierarchy
                    ORDER BY level, id;
                """
                hierarchy_records = await conn.fetch(hierarchy_query, int(job_id) if job_id.isdigit() else job_id)
                
                if not hierarchy_records:
                    return {"success": False, "error": "Website not found"}
                
                logger.info(f"🌳 Found {len(hierarchy_records)} pages in website hierarchy to delete")
                
                # Step 1: Delete all from FileSearch first
                genai_client = get_genai_client()
                filesearch_deleted = 0
                filesearch_errors = []
                
                for record in hierarchy_records:
                    metadata = record.get("metadata")
                    if metadata and genai_client:
                        try:
                            import json
                            if isinstance(metadata, str):
                                metadata_dict = json.loads(metadata)
                            else:
                                metadata_dict = metadata

                            if metadata_dict.get('type') == 'file_search' and metadata_dict.get('document_name'):
                                document_name = metadata_dict['document_name']
                                logger.info(f"🗑️ Deleting page {record['id']} (level {record['level']}) from FileSearch: {document_name}")
                                
                                # Use modern FileSearch API
                                genai_client.file_search_stores.documents.delete(
                                    name=document_name,
                                    force=True
                                )
                                filesearch_deleted += 1
                                logger.info(f"✅ Deleted from FileSearch: {document_name}")
                        except Exception as e:
                            if "404" in str(e) or "not found" in str(e).lower():
                                logger.warning(f"⚠️ FileSearch document already deleted for page {record['id']}: {e}")
                            else:
                                error_msg = f"Could not delete from FileSearch for page {record['id']}: {e}"
                                logger.error(f"❌ {error_msg}")
                                filesearch_errors.append(error_msg)
                
                # Step 2: Delete all from database (only if FileSearch deletion succeeded for most)
                if len(filesearch_errors) > len(hierarchy_records) / 2:
                    return {
                        "success": False, 
                        "error": f"Too many FileSearch deletion errors ({len(filesearch_errors)}/{len(hierarchy_records)}). Aborted database deletion."
                    }
                
                # Delete all records in the hierarchy
                delete_query = """
                    WITH RECURSIVE website_hierarchy AS (
                        SELECT id FROM scraped_websites WHERE id = $1
                        UNION ALL
                        SELECT w.id FROM scraped_websites w
                        INNER JOIN website_hierarchy wh ON w.parent_id = wh.id
                    )
                    DELETE FROM scraped_websites WHERE id IN (SELECT id FROM website_hierarchy)
                """
                result = await conn.execute(delete_query, int(job_id) if job_id.isdigit() else job_id)
                deleted_count = int(result.split()[-1]) if result else 0
                
                return {
                    "success": True, 
                    "message": f"Website hierarchy deleted successfully: {deleted_count} pages total",
                    "details": {
                        "total_pages": len(hierarchy_records),
                        "filesearch_deleted": filesearch_deleted,
                        "database_deleted": deleted_count,
                        "filesearch_errors": filesearch_errors
                    }
                }

        except Exception as e:
            logger.error(f"Error deleting website hierarchy {job_id}: {e}")
            return {"success": False, "error": str(e)}

    async def delete_job(self, job_id: str) -> Dict[str, Any]:
        """Delete a scraping job."""
        try:
            from shared.db import get_db_connection
            from website_crawling.core.ai import get_genai_client

            # First get the record to find FileSearch metadata
            job = await self.get_job_details(job_id)
            if not job:
                return {"success": False, "error": "Job not found"}

            # Delete from FileSearch first (if it has FileSearch metadata)
            metadata = job.get("metadata")
            if metadata:
                genai_client = get_genai_client()
                if genai_client:
                    try:
                        import json
                        if isinstance(metadata, str):
                            metadata_dict = json.loads(metadata)
                        else:
                            metadata_dict = metadata

                        if metadata_dict.get('type') == 'file_search' and metadata_dict.get('document_name'):
                            document_name = metadata_dict['document_name']
                            logger.info(f"🗑️ Deleting website from FileSearch: {document_name}")
                            
                            # Use modern FileSearch API
                            genai_client.file_search_stores.documents.delete(
                                name=document_name,
                                force=True
                            )
                            logger.info(f"✅ Deleted from FileSearch: {document_name}")
                    except Exception as e:
                        if "404" in str(e) or "not found" in str(e).lower():
                            logger.warning(f"⚠️ FileSearch document already deleted: {e}")
                        else:
                            logger.warning(f"⚠️ Could not delete from FileSearch: {e}")

            # Delete from database
            query = "DELETE FROM scraped_websites WHERE id = $1"
            async with get_db_connection() as conn:
                await conn.execute(query, int(job_id) if job_id.isdigit() else job_id)

            return {"success": True, "message": f"Job {job_id} deleted successfully"}

        except Exception as e:
            logger.error(f"Error deleting job {job_id}: {e}")
            return {"success": False, "error": str(e)}

    async def insert_scraped_metadata(self, metadata: Dict[str, Any]) -> str:
        """Insert scraped metadata using DAO."""
        try:
            record_id = await self.scraping_dao.record_scraped_metadata(metadata)
            return str(record_id) if record_id else None
        except Exception as e:
            logger.error(f"Error inserting scraped metadata: {e}")
            raise

    async def get_extracted_content(self, job_id: str, user_id: str, format: str = "json") -> Dict[str, Any]:
        """Get extracted content from a scraping job."""
        try:
            job = await self.get_job_details(job_id)
            if not job:
                return {"error": "Job not found"}

            return {
                "content": job.get("description", ""),
                "url": job.get("url"),
                "title": job.get("title"),
                "format": format
            }
        except Exception as e:
            logger.error(f"Error getting extracted content {job_id}: {e}")
            return {"error": str(e)}

    async def search_content(self, query: str, user_id: str, limit: int = 10) -> List[Dict[str, Any]]:
        """Search scraped content."""
        try:
            from shared.db import get_db_connection
            search_query = """
                SELECT id, original_url as url, domain, title, description,
                       pages_scraped, created_at
                FROM scraped_websites
                WHERE title ILIKE $1 OR domain ILIKE $1 OR original_url ILIKE $1
                ORDER BY created_at DESC
                LIMIT $2
            """
            async with get_db_connection() as conn:
                rows = await conn.fetch(search_query, f"%{query}%", limit)
                return [dict(row) for row in rows]
        except Exception as e:
            logger.error(f"Error searching content: {e}")
            return []

    async def get_analytics_summary(self, user_id: str) -> Dict[str, Any]:
        """Get scraping analytics summary."""
        try:
            from shared.db import get_db_connection
            query = """
                SELECT
                    COUNT(*) as total_jobs,
                    COALESCE(SUM(pages_scraped), 0) as total_pages_scraped,
                    COALESCE(SUM(content_length), 0) as total_content_length,
                    COUNT(CASE WHEN gemini_state = 'completed' THEN 1 END) as successful_jobs
                FROM scraped_websites
            """
            async with get_db_connection() as conn:
                row = await conn.fetchrow(query)
                if row:
                    total = row['total_jobs'] or 0
                    successful = row['successful_jobs'] or 0
                    return {
                        "total_jobs": total,
                        "total_pages_scraped": row['total_pages_scraped'],
                        "total_content_length": row['total_content_length'],
                        "success_rate": (successful / total * 100) if total > 0 else 100.0
                    }
            return {
                "total_jobs": 0,
                "total_pages_scraped": 0,
                "total_content_length": 0,
                "success_rate": 100.0
            }
        except Exception as e:
            logger.error(f"Error getting analytics summary: {e}")
            return {
                "total_jobs": 0,
                "total_pages_scraped": 0,
                "total_content_length": 0,
                "success_rate": 100.0
            }

    async def get_domain_analytics(self, user_id: str) -> Dict[str, Any]:
        """Get domain-specific analytics."""
        try:
            from shared.db import get_db_connection
            query = """
                SELECT domain, COUNT(*) as count, SUM(pages_scraped) as total_pages
                FROM scraped_websites
                GROUP BY domain
                ORDER BY count DESC
                LIMIT 20
            """
            async with get_db_connection() as conn:
                rows = await conn.fetch(query)
                return {
                    "domains": [
                        {
                            "domain": row['domain'],
                            "count": row['count'],
                            "total_pages": row['total_pages']
                        }
                        for row in rows
                    ]
                }
        except Exception as e:
            logger.error(f"Error getting domain analytics: {e}")
            return {"domains": []}

    # =================================
    # SESSION MANAGEMENT METHODS
    # =================================

    async def start_crawl_session(
        self, urls: List[str], user_id: str, options: Dict[str, Any]
    ) -> Dict[str, Any]:
        """
        Start a crawl session for multiple URLs.

        Args:
            urls: List of URLs to crawl
            user_id: User ID for tracking
            options: Crawling options (max_depth, max_pages_per_site, etc.)

        Returns:
            Dict with session details
        """
        try:
            session_id = str(uuid.uuid4())

            session_data = {
                "session_id": session_id,
                "user_id": user_id,
                "urls": urls,
                "options": options,
                "status": "running",
                "started_at": datetime.utcnow().isoformat(),
                "total_urls": len(urls),
                "completed_urls": 0,
                "failed_urls": 0,
                "results": [],
                "errors": []
            }

            _active_sessions[session_id] = session_data

            logger.info(f"🚀 Starting crawl session {session_id} for {len(urls)} URLs")

            # Start background task to process URLs
            asyncio.create_task(self._process_crawl_session(session_id))

            return {
                "success": True,
                "session_id": session_id,
                "message": "Crawl session started successfully",
                "total_urls": len(urls),
                "status": "running"
            }

        except Exception as e:
            logger.error(f"Error starting crawl session: {e}")
            raise

    async def _process_crawl_session(self, session_id: str):
        """Background task to process all URLs in a crawl session."""
        session = _active_sessions.get(session_id)
        if not session:
            logger.error(f"Session {session_id} not found")
            return

        urls = session["urls"]
        options = session["options"]

        max_pages_per_site = options.get("max_pages_per_site", 20)
        max_depth = options.get("max_depth", 2)
        delay_between_requests = options.get("delay_between_requests", 1)

        logger.info(f"📋 Processing {len(urls)} URLs for session {session_id}")

        for i, url in enumerate(urls):
            # Check if session was stopped
            current_session = _active_sessions.get(session_id)
            if not current_session or current_session.get("status") == "stopped":
                logger.info(f"⏹️ Session {session_id} was stopped")
                break

            logger.info(f"🔄 Processing URL {i+1}/{len(urls)}: {url}")

            try:
                # Scrape the website
                scrape_options = {
                    "max_pages": max_pages_per_site,
                    "max_depth": max_depth,
                    "replace_existing": False,
                    "timeout": 30,
                    "user_email": session.get("user_id")
                }

                result = await self.scrape_website(url, scrape_options)

                if result.get("success"):
                    session["completed_urls"] += 1
                    session["results"].append({
                        "url": url,
                        "status": "success",
                        "pages_scraped": result.get("pages_scraped", 0),
                        "job_id": result.get("job_id"),
                        "record_id": result.get("record_id")
                    })
                    logger.info(f"✅ Successfully scraped {url}")
                else:
                    session["failed_urls"] += 1
                    session["errors"].append({
                        "url": url,
                        "error": result.get("error", "Unknown error")
                    })
                    logger.warning(f"⚠️ Failed to scrape {url}: {result.get('error')}")

            except Exception as e:
                session["failed_urls"] += 1
                session["errors"].append({
                    "url": url,
                    "error": str(e)
                })
                logger.error(f"❌ Error scraping {url}: {e}")

            # Update session
            _active_sessions[session_id] = session

            # Delay between requests to be respectful
            if i < len(urls) - 1:
                await asyncio.sleep(delay_between_requests)

        # Mark session as completed
        session["status"] = "completed"
        session["completed_at"] = datetime.utcnow().isoformat()
        _active_sessions[session_id] = session

        logger.info(f"🏁 Session {session_id} completed: {session['completed_urls']} successful, {session['failed_urls']} failed")

    async def get_all_sessions(self) -> List[Dict[str, Any]]:
        """Get all crawl sessions."""
        try:
            sessions = []
            for session_id, session_data in _active_sessions.items():
                sessions.append({
                    "session_id": session_id,
                    "user_id": session_data.get("user_id"),
                    "status": session_data.get("status"),
                    "total_urls": session_data.get("total_urls", 0),
                    "completed_urls": session_data.get("completed_urls", 0),
                    "failed_urls": session_data.get("failed_urls", 0),
                    "started_at": session_data.get("started_at"),
                    "completed_at": session_data.get("completed_at")
                })

            # Sort by started_at (most recent first)
            sessions.sort(key=lambda x: x.get("started_at", ""), reverse=True)

            return sessions

        except Exception as e:
            logger.error(f"Error getting all sessions: {e}")
            return []

    async def get_session_details(
        self, session_id: str, user_id: str
    ) -> Optional[Dict[str, Any]]:
        """Get details of a crawl session."""
        try:
            session = _active_sessions.get(session_id)
            if not session:
                logger.warning(f"Session {session_id} not found")
                return None

            return {
                "session_id": session_id,
                "user_id": session.get("user_id"),
                "urls": session.get("urls", []),
                "status": session.get("status"),
                "total_urls": session.get("total_urls", 0),
                "completed_urls": session.get("completed_urls", 0),
                "failed_urls": session.get("failed_urls", 0),
                "started_at": session.get("started_at"),
                "completed_at": session.get("completed_at"),
                "results": session.get("results", []),
                "errors": session.get("errors", []),
                "options": session.get("options", {})
            }

        except Exception as e:
            logger.error(f"Error getting session details: {e}")
            return None

    async def stop_session(self, session_id: str, user_id: str) -> Dict[str, Any]:
        """Stop a running crawl session."""
        try:
            session = _active_sessions.get(session_id)
            if not session:
                return {
                    "success": False,
                    "error": "Session not found"
                }

            if session.get("status") == "completed":
                return {
                    "success": False,
                    "error": "Session already completed"
                }

            session["status"] = "stopped"
            session["completed_at"] = datetime.utcnow().isoformat()
            _active_sessions[session_id] = session

            logger.info(f"⏹️ Session {session_id} stopped by user")

            return {
                "success": True,
                "message": f"Session {session_id} stopped successfully"
            }

        except Exception as e:
            logger.error(f"Error stopping session: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    async def cleanup_old_sessions(self, max_age_hours: int = 24):
        """Clean up old completed sessions from memory."""
        try:
            current_time = datetime.utcnow()
            sessions_to_remove = []

            for session_id, session_data in _active_sessions.items():
                if session_data.get("status") in ["completed", "stopped"]:
                    completed_at = session_data.get("completed_at")
                    if completed_at:
                        completed_time = datetime.fromisoformat(completed_at)
                        age_hours = (current_time - completed_time).total_seconds() / 3600

                        if age_hours > max_age_hours:
                            sessions_to_remove.append(session_id)

            for session_id in sessions_to_remove:
                del _active_sessions[session_id]
                logger.info(f"🧹 Cleaned up old session {session_id}")

            return {
                "success": True,
                "cleaned_up": len(sessions_to_remove)
            }

        except Exception as e:
            logger.error(f"Error cleaning up sessions: {e}")
            return {
                "success": False,
                "error": str(e)
            }


# Singleton instance
website_service = WebsiteService()
