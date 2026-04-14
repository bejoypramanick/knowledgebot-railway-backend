"""
Website Processing Service for Celery Web Worker
Handles website scraping, extraction, and pgvector ingestion.
"""
import asyncio
import time
import os
import json
from datetime import datetime
from typing import Dict, List, Any, Optional, AsyncGenerator, Tuple
import logging
import hashlib
from shared.otel_logger import get_otel_logger
from urllib.parse import urljoin, urlparse
from shared.file_metrics import calculate_metrics
from shared.kreuzberg_integration import process_with_kreuzberg
from shared.html_cleaner import clean_html_with_trafilatura
from shared.s3_file_storage import s3_file_storage

from models.value_objects import (
    CrawlConfig,
    JobContext,
    PageData,
    UploadResult,
    PageMetrics,
    ProcessingResult,
    ProcessingRequest,
)

logger = get_otel_logger("processing_service", "celery-web-worker")

# Reduce crawl4ai logging verbosity (it logs database migrations at INFO level)
logging.getLogger('crawl4ai').setLevel(logging.WARNING)

CRAWL4AI_FETCH_RETRIES = int(os.environ.get("CRAWL4AI_FETCH_RETRIES", "2"))
CRAWL4AI_FETCH_RETRY_DELAY_SECONDS = float(os.environ.get("CRAWL4AI_FETCH_RETRY_DELAY_SECONDS", "2"))
CRAWL4AI_DEFAULT_USER_AGENT = os.environ.get(
    "CRAWL4AI_USER_AGENT",
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
)
CRAWL4AI_DEFAULT_WAIT_UNTIL = os.environ.get("CRAWL4AI_WAIT_UNTIL", "networkidle")
CRAWL4AI_DEFAULT_PAGE_TIMEOUT_MS = int(os.environ.get("CRAWL4AI_PAGE_TIMEOUT_MS", "90000"))
CRAWL4AI_DEFAULT_DELAY_BEFORE_HTML = float(os.environ.get("CRAWL4AI_DELAY_BEFORE_HTML", "1.5"))
CRAWL4AI_DEFAULT_LOCALE = os.environ.get("CRAWL4AI_LOCALE", "en-US")
CRAWL4AI_DEFAULT_TIMEZONE_ID = os.environ.get("CRAWL4AI_TIMEZONE_ID", "America/New_York")


def _env_bool(name: str, default: bool) -> bool:
    value = os.environ.get(name)
    if value is None:
        return default
    return value.strip().lower() in {"1", "true", "yes", "on"}


def _json_env(name: str, default: Any) -> Any:
    raw_value = os.environ.get(name)
    if not raw_value:
        return default
    try:
        return json.loads(raw_value)
    except json.JSONDecodeError as exc:
        logger.warning(f"⚠️ Invalid JSON in {name}; ignoring value: {exc}")
        return default


class ProcessingService:
    """Handle website scraping and content processing with value objects"""

    def __init__(self):
        from dao.scraping_dao import ScrapingDAO
        self.scraping_dao = ScrapingDAO()

    # ==================== MAIN ORCHESTRATOR ====================

    async def process_website_content(
        self,
        request: ProcessingRequest
    ) -> Dict[str, Any]:
        """
        Main orchestration: Resolve dependencies → Stream pages → Return result

        This is the entry point for website scraping. It coordinates the entire pipeline:
        1. RESOLVE: Validate request dependencies and user context
        2. STREAM: Process each page (crawl → extract content → upload → record in DB)
        3. RETURN: Build success/error result

        Aggregate statistics are calculated from child page records on-demand, avoiding
        redundant data storage in parent record. Each page record contains full metrics.

        The pipeline uses a streaming approach (async generator) to process one page at a
        time, avoiding loading all pages into memory. This enables processing of
        large websites with minimal memory footprint.

        Args:
            request (ProcessingRequest): Immutable request containing:
                - website_id: ID of website being processed
                - url: Root URL to start scraping
                - crawl_config: BFS crawl parameters (depth, max pages, etc.)
                - user_email: Email of user initiating scrape
                - user_role_id: Optional user role for filtering
                - celery_task_id: Task ID for cancellation checking
                - replace_existing: Whether to replace existing data
                - options: Additional options dict

        Returns:
            Dict[str, Any]: ProcessingResult as dict containing:
                - success: bool indicating if processing succeeded
                - website_id: ID of processed website
                - message: Human-readable status message
                - page_count: Number of pages successfully uploaded
                - total_size_bytes: Total content size processed
                - total_char_count: Total characters processed
                - processing_time_seconds: Elapsed time
                - error: Error message if failed, None if succeeded

        Raises:
            Exception: Any error during processing is caught and returned in result
        """
        start_time = time.time()
        try:
            # ========== PHASE 1: RESOLVE DEPENDENCIES ==========
            # Resolve access-control context before starting the crawl.

            logger.info(f"🚀 [SCRAPING] Starting website processing: {request.website_id}")
            logger.info(f"   URL: {request.url}")
            logger.info(f"   Depth: {request.crawl_config.max_depth}, Max Pages: {request.crawl_config.max_pages}")

            # Resolve user role ID for access control
            # Returns None if not found (NULL is allowed in schema)
            resolved_user_role_id = await self._resolveUserRoleID(request.user_email, request.user_role_id)

            # Build JobContext: Immutable object passed to all sub-operations
            # Contains: website_id, root_url, task_id, store, user_role
            # This reduces parameter passing and makes data flow explicit
            job_context = JobContext(
                website_id=request.website_id,
                root_url=request.url,
                celery_task_id=request.celery_task_id,
                store_name="pgvector",
                user_role_id=resolved_user_role_id
            )

            # ========== PHASE 2: STREAM PAGES ==========
            # Process pages one-at-a-time using async generator.
            # For each page: crawl → extract text → upload to Gemini → record in DB
            #
            # Memory efficiency:
            # - Old approach: crawl ALL → store in list → process all (500+ pages in RAM)
            # - New approach: crawl ONE → process ONE → record ONE → next (5 pages in RAM)
            # This achieves ~100x memory reduction for large sites.
            #
            # Returns: page count for logging only
            # Aggregate stats are queried from child records in database on-demand

            pages_uploaded = await self._crawlWebsitePages(
                crawl_config=request.crawl_config,
                job_context=job_context,
                options=request.options or {},
            )

            # ========== PHASE 2.5: CHECK PARENT COMPLETION ==========
            # Now that ALL pages have been discovered and processed, check if parent should be marked completed
            # This must happen AFTER crawling finishes to avoid premature completion
            # Add delay to ensure all database writes are fully committed and visible
            logger.info(f"🔍 [PARENT_COMPLETION_CHECK] All {pages_uploaded} pages crawled")
            logger.info(f"🔍 [PARENT_COMPLETION_CHECK] Waiting 3 seconds for all DB writes to commit...")
            await asyncio.sleep(3.0)  # Increased delay to ensure DB consistency
            
            logger.info(f"🔍 [PARENT_COMPLETION_CHECK] Now checking parent completion status for website {job_context.website_id}")
            parent_completed = await self.scraping_dao.check_and_update_parent_completion(job_context.website_id)
            
            if parent_completed:
                logger.info(f"✅ [PARENT_COMPLETION_CHECK] Parent {job_context.website_id} marked as completed")
            else:
                logger.info(f"ℹ️  [PARENT_COMPLETION_CHECK] Parent {job_context.website_id} not marked as completed (may have children still processing)")

            # ========== PHASE 3: BUILD SUCCESS RESULT ==========
            # Build simple success result for Celery task logging.
            # Actual aggregate statistics are calculated from child records (SUM queries).
            # WebsiteService also calls update_website_status() in database.

            processing_time = time.time() - start_time
            result = ProcessingResult(
                success=True,
                website_id=request.website_id,
                message=f"Website processed successfully: {pages_uploaded} pages",
                page_count=pages_uploaded,
                total_size_bytes=0,
                total_char_count=0,
                processing_time_seconds=processing_time
            )

            logger.info(f"✅ [COMPLETE] Website {request.website_id} processed: {pages_uploaded} pages in {processing_time:.1f}s")

            return result.to_dict()

        except Exception as e:
            # ========== ERROR HANDLING ==========
            # Catch any error and return failure result.
            # Note: No re-raise. Errors are caught and logged by Celery task handler.
            # WebsiteService.process_website_async() will call update_website_status('failed').

            processing_time = time.time() - start_time
            result = ProcessingResult(
                success=False,
                website_id=request.website_id,
                message="Processing failed",
                page_count=0,
                total_size_bytes=0,
                total_char_count=0,
                processing_time_seconds=processing_time,
                error=str(e)
            )
            logger.error(f"❌ Processing error: {e}")
            return result.to_dict()

    async def _crawlWebsitePages(
            self,
            crawl_config: CrawlConfig,
            job_context: JobContext,
            options: Optional[Dict[str, Any]] = None,
        ) -> int:
            """Stream each page: crawl → process → upload → record. Return page count only."""
            pages_uploaded = 0
            start_time = time.time()
            self._last_fetch_error = None

            logger.info(f"📄 [PIPELINE] Starting page-by-page streaming...")

            async for page_data in self._crawlPagesWithBFS(crawl_config, job_context, options or {}):
                metrics = await self._processPageInPipeline(page_data, job_context, crawl_config)
                if metrics:
                    pages_uploaded += 1

            if pages_uploaded == 0:
                last_error = getattr(self, "_last_fetch_error", None)
                if last_error:
                    raise Exception(f"No pages successfully processed. Last fetch error: {last_error}")
                raise Exception("No pages successfully processed")

            total_time = time.time() - start_time
            logger.info(f"✅ [PIPELINE] Completed: {pages_uploaded} pages in {total_time:.1f}s")

            return pages_uploaded


    async def _processPageInPipeline(
            self,
            page_data: PageData,
            job_context: JobContext,
            crawl_config: CrawlConfig
        ) -> Optional[PageMetrics]:
            """Process one page: convert (kreuzberg) → upload → record"""
            logger.info(f"📄 [PIPELINE] Processing: {page_data.page_url}")

            try:
                start_time = time.time()

                # Convert HTML to markdown via kreuzberg
                # HTML is pre-cleaned by crawl4ai (menus, navbars, ads removed)
                try:
                    markdown_content, processed_content_s3_key, chunks = await self._preparePageAsMarkdown(
                        page_data.page_html, page_data.page_url, website_id=job_context.website_id, remove_ads=True
                    )
                except Exception as kreuzberg_error:
                    logger.error(f"   ❌ Kreuzberg processing failed: {kreuzberg_error}")
                    logger.warning(f"   ⏭️ Skipping page due to kreuzberg error")
                    return None

                page_data = PageData(
                    page_url=page_data.page_url,
                    page_html=page_data.page_html,
                    markdown=markdown_content,
                    title=page_data.title,
                    description=page_data.description,
                    session_id=page_data.session_id
                )

                # Upload chunks to Vector DB
                from shared.vector_dao import vector_dao
                
                # Check if we have chunks
                if chunks:
                    # Generate embeddings using our model-agnostic utility
                    logger.info(f"🧬 Generating embeddings for {len(chunks)} chunks from {page_data.page_url}...")
                    from shared.embeddings import batch_generate_embeddings
                    chunk_texts = [c.get("text") or c.get("content", "") for c in chunks]
                    
                    # Pass source information for better usage observability
                    usage_metadata = {
                        "source_url": page_data.page_url,
                        "webpage_name": page_data.title,
                        "website_id": str(job_context.website_id),
                        "ingestion_workflow": "web_scrape_pipeline"
                    }
                    logger.info(f"🧬 Sending embedding request with metadata: {usage_metadata}")
                    embeddings = await batch_generate_embeddings(chunk_texts, request_metadata=usage_metadata)
                    
                    # Attach embeddings to chunks
                    for i, embedding in enumerate(embeddings):
                        if i < len(chunks):
                            chunks[i]["embedding"] = embedding

                    success = await vector_dao.batch_insert_chunks(
                        chunks=chunks, 
                        document_id=job_context.website_id,
                        document_type='website'
                    )
                    if not success:
                        logger.warning(f"   ⚠️ Chunk batch insert failed, skipping this page")
                        return None
                    logger.info(f"   ✅ Uploaded {len(chunks)} chunks with OpenAI embeddings to vector DB")
                else:
                    logger.error(f"   ❌ No chunks produced by Kreuzberg for {page_data.page_url}")
                    raise Exception(f"No chunks produced by extractor for {page_data.page_url}")

                self._current_page_data = page_data
                
                # Create a mock upload result for backwards compatibility with _recordPageToDB
                upload_result = UploadResult(
                    document_name=f"vector_db_{job_context.website_id}",
                    storage_backend_name="pgvector",
                    uploaded_at=datetime.utcnow(),
                    storage_document_uri=f"vector_db_{job_context.website_id}",
                    confirmed=True,
                    metadata_type="vector_db",
                    extra_metadata={
                        "grounding_source": "pgvector",
                        "retrieval_pipeline": "kreuzberg_rust -> pgvector",
                    },
                )

                # Delete processed markdown from S3 (now safely represented in vector storage)
                # Check RETAIN_MD_FILE environment variable to decide whether to delete
                # Note: Manual atomic delete operations will still delete retained files
                retain_md_file = os.getenv("RETAIN_MD_FILE", "false").lower() == "true"
                
                if processed_content_s3_key:
                    if retain_md_file:
                        logger.info(f"📁 [MD_RETENTION] Retaining processed markdown in S3: {processed_content_s3_key}")
                        logger.info(f"   RETAIN_MD_FILE=true - file will be available as attachment")
                    else:
                        try:
                            deleted = await s3_file_storage.delete_file(processed_content_s3_key)
                            if deleted:
                                logger.info(f"   🧹 [S3_CLEANUP] Deleted processed markdown: {processed_content_s3_key}")
                            else:
                                logger.warning(f"   ⚠️ [S3_CLEANUP] Failed to delete processed markdown: {processed_content_s3_key}")
                        except Exception as cleanup_err:
                            logger.warning(f"   ⚠️ [S3_CLEANUP] Error deleting processed markdown: {cleanup_err}")

                # Record to database
                await self._recordPageToDB(page_data, upload_result, job_context, crawl_config, processed_content_s3_key)

                # Metrics
                metrics = calculate_metrics(markdown_content)
                processing_time = time.time() - start_time

                return PageMetrics(
                    file_size_bytes=metrics.get('file_size_bytes', 0),
                    char_count=metrics.get('char_count', 0),
                    processing_time_seconds=processing_time
                )
            except Exception as e:
                logger.error(f"   ❌ Pipeline error: {e}")
                return None


    # ==================== CRAWL LAYER ====================

    def _isSitemapURL(self, url: str) -> bool:
        """Check if URL is a sitemap"""
        url_lower = url.lower()
        return (
            url_lower.endswith('sitemap.xml') or
            url_lower.endswith('sitemap.xml.gz') or
            url_lower.endswith('sitemap_index.xml') or
            '/sitemap' in url_lower and url_lower.endswith('.xml')
        )

    async def _discoverSitemapURLs(
        self,
        sitemap_url: str,
        max_urls: int = 100
    ) -> List[str]:
        """
        Discover URLs from a sitemap by directly parsing the XML.
        
        Args:
            sitemap_url: Full URL of the sitemap
            max_urls: Maximum URLs to extract
            
        Returns:
            List of URLs found in the sitemap
        """
        try:
            import xml.etree.ElementTree as ET
            import aiohttp
            import gzip
            from io import BytesIO
            
            logger.info(f"🗺️ [SITEMAP] Discovering URLs from {sitemap_url}")
            logger.info(f"   Max URLs: {max_urls}")
            
            # Fetch the sitemap
            async with aiohttp.ClientSession() as session:
                async with session.get(sitemap_url, timeout=aiohttp.ClientTimeout(total=30)) as response:
                    if response.status != 200:
                        logger.error(f"❌ [SITEMAP] Failed to fetch sitemap: HTTP {response.status}")
                        return []
                    
                    content = await response.read()
                    
                    # Handle compressed sitemaps
                    if sitemap_url.endswith('.gz'):
                        logger.info(f"📦 [SITEMAP] Decompressing gzipped sitemap")
                        content = gzip.decompress(content)
                    
                    # Parse XML
                    try:
                        root = ET.fromstring(content)
                    except ET.ParseError as e:
                        logger.error(f"❌ [SITEMAP] Failed to parse XML: {e}")
                        return []
                    
                    # Extract URLs from sitemap
                    urls = []
                    
                    # Handle namespace
                    namespaces = {
                        'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9',
                        'xhtml': 'http://www.w3.org/1999/xhtml'
                    }
                    
                    # Check if this is a sitemap index (contains other sitemaps)
                    sitemap_locs = root.findall('.//ns:sitemap/ns:loc', namespaces)
                    if sitemap_locs:
                        total_sitemaps = len(sitemap_locs)
                        logger.info(f"📋 [SITEMAP] Found sitemap index with {total_sitemaps} sub-sitemaps")
                        
                        # Process all sub-sitemaps (no arbitrary limit)
                        for idx, sitemap_loc in enumerate(sitemap_locs, 1):
                            if len(urls) >= max_urls:
                                logger.info(f"⚠️  [SITEMAP] Reached max_urls limit ({max_urls}), stopping at sub-sitemap {idx}/{total_sitemaps}")
                                break
                            
                            sub_sitemap_url = sitemap_loc.text.strip()
                            logger.info(f"   [{idx}/{total_sitemaps}] Fetching sub-sitemap: {sub_sitemap_url}")
                            
                            sub_urls = await self._discoverSitemapURLs(
                                sub_sitemap_url,
                                max_urls=max_urls - len(urls)
                            )
                            urls.extend(sub_urls)
                            logger.info(f"   [{idx}/{total_sitemaps}] Got {len(sub_urls)} URLs (total: {len(urls)}/{max_urls})")
                    else:
                        # Regular sitemap - extract <loc> elements
                        url_locs = root.findall('.//ns:url/ns:loc', namespaces)
                        
                        for url_loc in url_locs:
                            if len(urls) >= max_urls:
                                break
                            
                            url = url_loc.text.strip()
                            urls.append(url)
                    
                    logger.info(f"✅ [SITEMAP] Discovered {len(urls)} URLs from sitemap")
                    
                    # Log first few URLs as sample
                    if urls:
                        logger.info(f"📋 [SITEMAP] Sample URLs:")
                        for url in urls[:3]:
                            logger.info(f"   - {url}")
                    
                    return urls
                    
        except Exception as e:
            logger.error(f"❌ [SITEMAP] Failed to discover URLs: {e}")
            import traceback
            logger.error(f"   Traceback: {traceback.format_exc()}")
            return []

    async def _crawlPagesWithBFS(
        self,
        crawl_config: CrawlConfig,
        job_context: JobContext,
        options: Optional[Dict[str, Any]] = None,
    ) -> AsyncGenerator[PageData, None]:
        """Async generator yielding PageData one at a time"""
        try:
            from crawl4ai import AsyncWebCrawler
        except ImportError as ie:
            logger.error(f"❌ crawl4ai not available: {ie}")
            return

        # Check if root URL is a sitemap
        is_sitemap = self._isSitemapURL(job_context.root_url)
        
        if is_sitemap:
            logger.info(f"🗺️ [SITEMAP] Detected sitemap URL, using URL discovery")
            
            # Discover URLs from sitemap
            sitemap_urls = await self._discoverSitemapURLs(
                job_context.root_url,
                max_urls=crawl_config.max_pages
            )
            
            if not sitemap_urls:
                logger.error("❌ [SITEMAP] No URLs discovered from sitemap")
                return
            
            logger.info(f"📋 [SITEMAP] Will crawl {len(sitemap_urls)} URLs from sitemap")
            
            # Add all sitemap URLs to crawl queue (depth=1 for all)
            to_visit = [(url, 1) for url in sitemap_urls]
            visited_urls = set()
        else:
            # Normal BFS crawl
            visited_urls = set()
            to_visit = [(job_context.root_url, 0)]

        semaphore = asyncio.Semaphore(crawl_config.max_concurrent)
        pages_yielded = 0

        logger.info(f"🔄 Starting {'sitemap' if is_sitemap else 'BFS'} crawl with max_depth={crawl_config.max_depth}, max_pages={crawl_config.max_pages}")

        while to_visit and pages_yielded < crawl_config.max_pages:
            current_url, current_depth = to_visit.pop(0)

            if not await self._validateURLForCrawl(current_url, current_depth, crawl_config.max_depth, visited_urls):
                continue

            visited_urls.add(self._normalize_url(current_url))

            result = await self._fetchPageHTML(
                current_url,
                semaphore,
                crawl_config.delay_between_requests,
                options=options or {},
            )
            if result:
                page_url, page_html, title, description, session_id = result
                pages_yielded += 1
                logger.info(f"✅ [{'SITEMAP' if is_sitemap else 'BFS'}] Yielded page {pages_yielded}/{crawl_config.max_pages}")

                yield PageData(
                    page_url=page_url,
                    page_html=page_html,
                    title=title,
                    description=description,
                    session_id=session_id
                )

                # For sitemap crawls, don't follow links (we already have all URLs)
                # For normal BFS, continue following links
                if not is_sitemap and current_depth < crawl_config.max_depth and pages_yielded < crawl_config.max_pages:
                    new_links = await self._extractLinksFromHTML(page_html, page_url, self._get_domain(job_context.root_url), visited_urls)
                    to_visit.extend((link, current_depth + 1) for link in new_links if pages_yielded < crawl_config.max_pages)

    async def _validateURLForCrawl(self, url: str, depth: int, max_depth: int, visited_urls: set) -> bool:
        """Check if URL should be crawled"""
        normalized = self._normalize_url(url)

        if normalized in visited_urls:
            logger.info(f"⏭️  Already visited: {url}")
            return False

        if depth > max_depth:
            logger.info(f"⏭️  Depth exceeded: {url}")
            return False

        return True

    async def _fetchPageHTML(
        self,
        page_url: str,
        semaphore: asyncio.Semaphore,
        delay: float,
        options: Optional[Dict[str, Any]] = None,
    ) -> Optional[Tuple[str, str, Optional[str], Optional[str], Optional[str]]]:
        """
        Fetch single page via crawl4ai with HTML cleaning.

        Crawl4ai removes menus, navbars, ads via built-in cleaning options.
        Returns: (url, cleaned_html, title, description, session_id)
        """
        async with semaphore:
            from crawl4ai import AsyncWebCrawler, BrowserConfig, CrawlerRunConfig
            options = options or {}

            # JavaScript to unhide all hidden elements
            js_code = """
            document.querySelectorAll('table, p, div, span, [style*="display: none"], [style*="visibility: hidden"], .hidden, [hidden]').forEach(el => {
                el.style.display = el.tagName === 'TABLE' ? 'table' : 'block';
                el.style.visibility = 'visible !important';
                el.style.opacity = '1';
                el.hidden = false;
            });
            """

            headers = dict(_json_env("CRAWL4AI_HEADERS_JSON", {}) or {})
            headers.update(options.get("crawler_headers") or {})

            cookies = options.get("crawler_cookies")
            if cookies is None:
                cookies = _json_env("CRAWL4AI_COOKIES_JSON", None)

            browser_config = BrowserConfig(
                headless=True,
                user_agent=options.get("crawler_user_agent") or CRAWL4AI_DEFAULT_USER_AGENT,
                headers=headers or None,
                cookies=cookies,
                enable_stealth=bool(options.get(
                    "crawler_enable_stealth",
                    _env_bool("CRAWL4AI_ENABLE_STEALTH", True),
                )),
                viewport_width=int(options.get("crawler_viewport_width") or 1366),
                viewport_height=int(options.get("crawler_viewport_height") or 900),
            )
            run_config = CrawlerRunConfig(
                js_code=js_code,
                wait_until=options.get("crawler_wait_until") or CRAWL4AI_DEFAULT_WAIT_UNTIL,
                wait_for=options.get("crawler_wait_for"),
                wait_for_timeout=options.get("crawler_wait_for_timeout"),
                page_timeout=int(options.get("crawler_page_timeout") or CRAWL4AI_DEFAULT_PAGE_TIMEOUT_MS),
                delay_before_return_html=float(
                    options.get("crawler_delay_before_return_html")
                    or CRAWL4AI_DEFAULT_DELAY_BEFORE_HTML
                ),
                remove_overlay_elements=False,
                remove_forms=False,
                magic=bool(options.get("crawler_magic", _env_bool("CRAWL4AI_MAGIC", True))),
                simulate_user=bool(options.get(
                    "crawler_simulate_user",
                    _env_bool("CRAWL4AI_SIMULATE_USER", True),
                )),
                override_navigator=bool(options.get(
                    "crawler_override_navigator",
                    _env_bool("CRAWL4AI_OVERRIDE_NAVIGATOR", True),
                )),
                locale=options.get("crawler_locale") or CRAWL4AI_DEFAULT_LOCALE,
                timezone_id=options.get("crawler_timezone_id") or CRAWL4AI_DEFAULT_TIMEZONE_ID,
                user_agent=options.get("crawler_user_agent") or CRAWL4AI_DEFAULT_USER_AGENT,
            )
            attempts = max(1, CRAWL4AI_FETCH_RETRIES + 1)

            for attempt in range(1, attempts + 1):
                try:
                    async with AsyncWebCrawler(config=browser_config) as crawler:
                        # Get page as-is without any removal
                        # Extract text content from full page using Kreuzberg
                        logger.info(f"🔍 [CRAWL4AI] Fetching {page_url} (attempt {attempt}/{attempts})...")
                        result = await crawler.arun(
                            url=page_url,
                            config=run_config,
                        )

                        if result.success and result.html:
                            if delay > 0:
                                await asyncio.sleep(delay)
                            logger.info(f"✅ [CRAWL4AI] Fetched HTML: {len(result.html)} bytes from {page_url}")

                            # Extract title and description from metadata
                            title = None
                            description = None
                            if result.metadata:
                                title = result.metadata.get('title')
                                description = result.metadata.get('description')

                            return (page_url, result.html, title, description, result.session_id)

                        error_message = (
                            getattr(result, "error_message", None)
                            or getattr(result, "error", None)
                            or getattr(result, "status_code", None)
                            or "crawl4ai returned no HTML"
                        )
                        self._last_fetch_error = f"{page_url}: {error_message}"
                        logger.warning(
                            f"⚠️ [CRAWL4AI] Failed to fetch {page_url} "
                            f"(attempt {attempt}/{attempts}): {error_message}"
                        )
                except Exception as e:
                    self._last_fetch_error = f"{page_url}: {e}"
                    logger.error(f"❌ [CRAWL4AI] Error fetching {page_url} (attempt {attempt}/{attempts}): {e}")

                if attempt < attempts:
                    await asyncio.sleep(CRAWL4AI_FETCH_RETRY_DELAY_SECONDS * attempt)

            return None

    async def _extractLinksFromHTML(
        self, html: str, page_url: str, base_domain: str, visited_urls: set
    ) -> List[str]:
        """Parse HTML and return list of new, same-domain URLs"""
        try:
            from bs4 import BeautifulSoup
            soup = BeautifulSoup(html, 'lxml')

            links = []
            for a_tag in soup.find_all('a', href=True):
                href = self._resolvePageUrl(a_tag['href'], page_url)
                if self._isValidPageLink(href, base_domain, visited_urls):
                    links.append(href)

            logger.info(f"🔗 [LINKS] Found {len(links)} new links")
            return links
        except Exception as e:
            logger.warning(f"⚠️ Failed to extract links: {e}")
            return []

    def _resolvePageUrl(self, href: str, page_url: str) -> str:
        """Convert relative URL to absolute"""
        if href.startswith(('http://', 'https://')):
            return href
        if href.startswith('/'):
            domain = self._get_domain(page_url)
            return f"{domain}{href}"
        return urljoin(page_url, href)

    def _isValidPageLink(self, url: str, base_domain: str, visited_urls: set) -> bool:
        """Check if URL should be queued"""
        if self._get_domain(url) != base_domain:
            return False
        if self._normalize_url(url) in visited_urls:
            return False
        return True

    async def _preparePageAsMarkdown(self, html_content: str, page_url: str, website_id: Optional[str] = None, remove_ads: bool = True) -> Tuple[str, Optional[str], list]:
        """
        Process HTML with Kreuzberg, then chunk the returned markdown with Chonkie.
        """
        url_hash = hashlib.md5(page_url.encode()).hexdigest()[:12]
        if remove_ads:
            cleaned_html = clean_html_with_trafilatura(html_content, url=page_url)
            logger.info(
                f"🧭 [HTML_CLEAN] Trafilatura cleaned HTML (ads, menus, comments, footers removed)"
                f" | page_url={page_url}"
                f" | raw_html_chars={len(html_content)}"
                f" | cleaned_html_chars={len(cleaned_html)}"
            )
        else:
            cleaned_html = html_content
            logger.info(f"⏭️ [HTML_CLEAN] Skipping Trafilatura cleaning (remove_ads=False) | page_url={page_url}")
        html_filename = f"page_{url_hash}.html"
        html_upload_success, html_s3_key = await s3_file_storage.upload_file(
            file_data=cleaned_html.encode('utf-8'),
            original_filename=html_filename,
            file_type="web-worker-temp"
        )

        if not html_upload_success:
            raise Exception(f"Failed to upload HTML to S3 for {page_url}")

        logger.info(
            f"📦 [KREUZBERG] Temp HTML uploaded for extraction"
            f" | website_id={website_id}"
            f" | page_url={page_url}"
            f" | html_s3_key={html_s3_key}"
            f" | bucket={s3_file_storage.bucket_name}"
        )
        logger.info(f"🔍 [KREUZBERG] Verifying temp HTML exists before queueing extraction: {html_s3_key}")
        success, result = s3_file_storage.generate_presigned_url(
            html_s3_key,
            expiration=3600,
            verify_exists=True,
        )
        if not success:
            try:
                await s3_file_storage.delete_file(html_s3_key)
            except Exception:
                pass
            raise Exception(f"Failed to verify temp HTML {html_s3_key} before extraction: {result}")

        try:
            logger.info(
                f"📨 [KREUZBERG] Queueing extraction job"
                f" | website_id={website_id}"
                f" | page_url={page_url}"
                f" | html_s3_key={html_s3_key}"
                f" | bucket={s3_file_storage.bucket_name}"
            )
            kreuzberg_markdown, kreuzberg_metadata = await process_with_kreuzberg(
                s3_key=html_s3_key,
                original_filename=html_filename,
                mime_type="text/html",
                worker_type="web",
                source_id=website_id,
                source_name=page_url
            )

            if not kreuzberg_markdown:
                error_detail = kreuzberg_metadata.get('error', 'unknown') if kreuzberg_metadata else 'unknown'
                raise Exception(f"Kreuzberg processing failed for {page_url}: {error_detail}")

            markdown_content = kreuzberg_markdown
            chunks = kreuzberg_metadata.get("chunks") or []
            if not chunks:
                raise Exception(f"Kreuzberg returned no chunks for {page_url}")

            for chunk in chunks:
                if "metadata" not in chunk:
                    chunk["metadata"] = {}
                chunk["metadata"]["url"] = page_url
                if hasattr(self, "_current_page_data") and getattr(self._current_page_data, "title", None):
                    chunk["metadata"]["title"] = self._current_page_data.title

            md_filename = f"page_{url_hash}.md"
            md_success, md_s3_key = await s3_file_storage.upload_file(
                file_data=markdown_content.encode('utf-8'),
                original_filename=md_filename,
                file_type="processed"
            )

            processed_content_s3_key = md_s3_key if md_success else None

            try:
                await s3_file_storage.delete_file(html_s3_key)
            except Exception as cleanup_err:
                logger.warning(f"⚠️ [CLEANUP] Failed to delete temp HTML: {cleanup_err}")

            return markdown_content, processed_content_s3_key, chunks

        except Exception as kreuzberg_err:
            try:
                await s3_file_storage.delete_file(html_s3_key)
            except Exception:
                pass

            raise Exception(f"Kreuzberg processing failed for {page_url}: {kreuzberg_err}")

    async def _extractDocumentsFromPage(
        self, html_content: str, page_url: str, page_markdown: str
    ) -> str:
        """Extract embedded files from HTML if Kreuzberg enabled"""
        from core.config import settings

        if not settings.kreuzberg_enabled:
            logger.info("📄 [ROUTING] Kreuzberg processing disabled, keeping existing files.")
            return page_markdown

        try:
            file_links = await self._findDocumentLinksInHTML(html_content, page_url)
            if not file_links:
                return page_markdown

            extracted_docs = await self._processEmbeddedDocuments(file_links)
            return await self._appendDocumentsToMarkdown(page_markdown, extracted_docs)
        except Exception as e:
            logger.warning(f"⚠️ [KREUZBERG] Error: {e}")
            return page_markdown

    async def _findDocumentLinksInHTML(self, html_content: str, page_url: str) -> List[Dict]:
        """Find embedded files (PDF, DOCX, etc.) in HTML"""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, 'lxml')
        kreuzberg_supported = {'.pdf', '.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.xls'}

        file_links = []
        for link in soup.find_all('a', href=True):
            href = link['href']
            if not href.startswith(('http://', 'https://')):
                href = urljoin(page_url, href)

            if any(urlparse(href).path.lower().endswith(ext) for ext in kreuzberg_supported):
                file_links.append({'url': href, 'text': link.get_text(strip=True) or 'Document'})

        logger.info(f"📎 [KREUZBERG] Found {len(file_links)} embedded files")
        return file_links[:5]

    async def _processEmbeddedDocuments(self, file_links: List[Dict]) -> List[Dict]:
        """Process all files through kreuzberg service"""
        import httpx

        extracted_docs = []
        async with httpx.AsyncClient(timeout=60) as client:
            for file_link in file_links:
                doc = await self._processEmbeddedDocument(client, file_link)
                if doc:
                    extracted_docs.append(doc)

        return extracted_docs

    async def _processEmbeddedDocument(self, client: Any, file_link: Dict) -> Optional[Dict]:
        """Process single file through kreuzberg"""
        file_url = file_link['url']

        try:
            response = await client.get(file_url, timeout=30)
            if response.status_code != 200:
                logger.warning(f"⚠️ Failed to download {file_url}")
                return None

            if len(response.content) > 25 * 1024 * 1024:
                logger.warning(f"⚠️ File too large: {file_url}")
                return None

            return await self._downloadAndKreuzbergProcess(response.content, file_url, file_link)
        except Exception as e:
            logger.warning(f"⚠️ Error processing {file_url}: {e}")
            return None

    async def _downloadAndKreuzbergProcess(self, file_bytes: bytes, file_url: str, file_link: Dict) -> Optional[Dict]:
        """Upload file to S3 and process through Kreuzberg"""
        filename = os.path.basename(urlparse(file_url).path)
        _, file_ext = os.path.splitext(filename.lower())
        
        mime_types = {
            '.pdf': 'application/pdf',
            '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
            '.doc': 'application/msword',
            '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
            '.ppt': 'application/vnd.ms-powerpoint',
            '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            '.xls': 'application/vnd.ms-excel',
        }
        mime_type = mime_types.get(file_ext, 'application/octet-stream')

        logger.info(f"📤 [KREUZBERG_EMBEDDED] Processing embedded document: {filename}")

        try:
            # 1. Upload to S3 temporarily
            success, s3_key = await s3_file_storage.upload_file(
                file_data=file_bytes,
                original_filename=filename,
                file_type="web-worker-temp"
            )
            
            if not success:
                logger.error(f"❌ [KREUZBERG_EMBEDDED] Failed to upload {filename} to S3")
                return None

            # 2. Verify object exists before queueing extraction
            verify_success, verify_result = s3_file_storage.generate_presigned_url(s3_key, verify_exists=True)
            if not verify_success:
                logger.error(f"❌ [KREUZBERG_EMBEDDED] Failed to verify temp S3 object for {filename}: {verify_result}")
                await s3_file_storage.delete_file(s3_key)
                return None

            # 3. Process with Kreuzberg
            markdown_content, _ = await process_with_kreuzberg(
                s3_key=s3_key,
                original_filename=filename,
                mime_type=mime_type,
                worker_type="web"
            )

            # 4. Cleanup S3
            await s3_file_storage.delete_file(s3_key)

            if markdown_content:
                logger.info(f"✅ [KREUZBERG_EMBEDDED] Extracted {len(markdown_content)} characters")
                return {'title': file_link['text'], 'filename': filename, 'content': markdown_content}

            return None
        except Exception as e:
            logger.error(f"❌ [KREUZBERG_EMBEDDED] Error processing {filename}: {e}")
            return None

    async def _appendDocumentsToMarkdown(self, page_markdown: str, extracted_docs: List[Dict]) -> str:
        """Append extracted documents to page markdown"""
        if not extracted_docs:
            return page_markdown

        page_markdown += "\n\n---\n\n## Embedded Documents\n\n"

        for doc in extracted_docs:
            page_markdown += f"### {doc['title']}\n"
            page_markdown += f"*Source: {doc['filename']}*\n\n"
            page_markdown += doc['content']
            page_markdown += "\n\n"

        return page_markdown

    # ==================== ACCESS LAYER ====================

    async def _resolveUserRoleID(self, user_email: str, user_role_id: Optional[str] = None) -> Optional[str]:
        """Resolve user_role_id (allow NULL if not found)"""
        if user_role_id:
            logger.info(f"✅ Using provided user_role_id: {user_role_id}")
            return user_role_id

        user_role_id = await self.scraping_dao.get_admin_user_role_id(user_email)
        if not user_role_id:
            logger.warning(f"⚠️ No user role found, will use NULL")

        return user_role_id

    async def _deleteTemporaryFile(self, temp_file: str):
        """Clean up temporary file"""
        try:
            os.unlink(temp_file)
        except:
            pass

    # ==================== DATABASE LAYER ====================

    async def _recordPageToDB(
            self,
            page_data: PageData,
            upload_result: UploadResult,
            job_context: JobContext,
            crawl_config: CrawlConfig,
            processed_content_s3_key: Optional[str] = None
        ) -> Optional[str]:
            """Record single page in database"""
            storage_backend_state = 'completed' if getattr(upload_result, "confirmed", False) else 'pending'
            metrics = calculate_metrics(page_data.markdown)
            
            if await self._isSinglePageMode(page_data.page_url, job_context.root_url, crawl_config):
                logger.info(f"   ℹ️ Single-page mode: updating parent record with page data")

                # Update the parent website record with the page data
                # Mark as completed since single-page mode has no children
                await self._updateWebsiteWithPageData(
                    website_id=job_context.website_id,
                    page_data=page_data,
                    upload_result=upload_result,
                    file_size=metrics.get('file_size_bytes', 0),
                    char_count=metrics.get('char_count', 0),
                    mark_completed=True,  # Single-page mode - mark as completed
                    processed_content_s3_key=processed_content_s3_key,
                    storage_backend_state=storage_backend_state
                )

                # Cache citation URL mappings in Redis for fast lookup during chat
                try:
                    from shared.redis_citation_cache import cache_single_url
                    if upload_result.display_name and page_data.page_url:
                        await cache_single_url(upload_result.display_name, page_data.page_url)
                    if upload_result.document_name and page_data.page_url:
                        await cache_single_url(upload_result.document_name, page_data.page_url)
                except Exception as cache_err:
                    logger.warning(f"⚠️ Citation cache update failed (non-blocking): {cache_err}")

                return job_context.website_id

            # Check if this is the root URL in multi-page mode
            # If so, update the parent record instead of creating a child
            # Normalize both URLs for comparison to handle trailing slashes
            if self._normalize_url(page_data.page_url) == self._normalize_url(job_context.root_url):
                logger.info(f"   ℹ️ Root URL in multi-page mode: updating parent record")
                
                # Update the parent website record with the root page data
                # Do NOT mark as completed - children are still being processed
                await self._updateWebsiteWithPageData(
                    website_id=job_context.website_id,
                    page_data=page_data,
                    upload_result=upload_result,
                    file_size=metrics.get('file_size_bytes', 0),
                    char_count=metrics.get('char_count', 0),
                    mark_completed=False,  # Multi-page mode - keep status as 'processing'
                    processed_content_s3_key=processed_content_s3_key,
                    storage_backend_state=storage_backend_state
                )

                # Cache citation URL mappings in Redis for fast lookup during chat
                try:
                    from shared.redis_citation_cache import cache_single_url
                    if upload_result.display_name and page_data.page_url:
                        await cache_single_url(upload_result.display_name, page_data.page_url)
                    if upload_result.document_name and page_data.page_url:
                        await cache_single_url(upload_result.document_name, page_data.page_url)
                except Exception as cache_err:
                    logger.warning(f"⚠️ Citation cache update failed (non-blocking): {cache_err}")

                return job_context.website_id

            # This is a child page - record it as such
            child_page_id = await self.scraping_dao.record_child_page(
                parent_id=job_context.website_id,
                page_url=page_data.page_url,
                storage_document_name=upload_result.document_name,
                storage_document_uri=upload_result.storage_document_uri,
                storage_metadata=upload_result.storage_metadata,
                user_role_id=job_context.user_role_id,
                file_size=metrics.get('file_size_bytes', 0),
                char_count=metrics.get('char_count', 0),
                title=page_data.title,
                description=page_data.description,
                crawl_session_id=page_data.session_id,
                processed_content_s3_key=processed_content_s3_key,
                storage_backend_state=storage_backend_state
            )

            # Cache citation URL mappings in Redis for fast lookup during chat
            try:
                from shared.redis_citation_cache import cache_single_url
                if upload_result.display_name and page_data.page_url:
                    await cache_single_url(upload_result.display_name, page_data.page_url)
                if upload_result.document_name and page_data.page_url:
                    await cache_single_url(upload_result.document_name, page_data.page_url)
            except Exception as cache_err:
                logger.warning(f"⚠️ Citation cache update failed (non-blocking): {cache_err}")

            # Don't check parent completion here - it will be checked after ALL pages are crawled
            # Checking here causes premature completion when not all pages have been discovered yet

            return child_page_id


    async def _isSinglePageMode(self, page_url: str, root_url: str, crawl_config: CrawlConfig) -> bool:
            """
            Check if this is truly single-page mode.

            Single-page mode means:
            1. The page URL matches the root URL (it's the first/only page)
            2. AND max_depth is 0 (no crawling of child pages)

            This prevents the first page of a multi-page crawl from being
            incorrectly treated as single-page mode.
            """
            # Normalize URLs for comparison to handle trailing slashes
            is_root_page = self._normalize_url(page_url) == self._normalize_url(root_url)
            is_depth_zero = crawl_config.max_depth == 0

            result = is_root_page and is_depth_zero

            if is_root_page and not is_depth_zero:
                logger.info(f"   ℹ️ Root page detected but max_depth={crawl_config.max_depth} - NOT single-page mode")

            return result


    async def _updateWebsiteWithPageData(
        self,
        website_id: str,
        page_data: PageData,
        upload_result: UploadResult,
        file_size: int,
        char_count: int,
        mark_completed: bool = True,
        processed_content_s3_key: Optional[str] = None,
        storage_backend_state: str = 'completed'
    ) -> bool:
        """Update parent website record with single page data"""
        logger.info(f"💾 [UPDATE_WEBSITE] Updating website {website_id} with page data")

        return await self.scraping_dao.update_website_with_page_data(
            website_id=website_id,
            storage_document_name=upload_result.document_name,
            storage_document_uri=upload_result.storage_document_uri,
            file_size=file_size,
            char_count=char_count,
            title=page_data.title,
            description=page_data.description,
            crawl_session_id=page_data.session_id,
            storage_metadata=upload_result.storage_metadata,
            mark_completed=mark_completed,
            processed_content_s3_key=processed_content_s3_key,
            storage_backend_state=storage_backend_state
        )

    # ==================== UTILITIES ====================

    @staticmethod
    def _get_domain(url: str) -> str:
        """Extract domain from URL"""
        try:
            parsed = urlparse(url)
            return f"{parsed.scheme}://{parsed.netloc}"
        except:
            return url

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize URL for consistent deduplication"""
        try:
            from urllib.parse import urlparse, urlunparse

            parsed = urlparse(url)
            normalized = urlunparse((parsed.scheme, parsed.netloc, parsed.path, '', '', ''))

            if normalized.endswith('/') and not normalized.endswith('://'):
                if parsed.path not in ('/', ''):
                    normalized = normalized.rstrip('/')
            elif not normalized.endswith('/') and not parsed.path:
                normalized += '/'

            return normalized.lower()
        except:
            return url.lower()
