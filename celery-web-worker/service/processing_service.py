"""
Website Processing Service for Celery Web Worker
Handles all website scraping, content extraction, and Gemini FileSearch upload
with extreme single-responsibility, minimal method size, and value objects
"""
import asyncio
import time
import os
import tempfile
from datetime import datetime
from typing import Dict, List, Any, Optional, AsyncGenerator, Tuple
import logging
from urllib.parse import urljoin, urlparse

from shared.otel_logger import get_otel_logger
from shared.file_search import get_file_search_store_by_display_name
from shared.file_metrics import calculate_metrics
from shared.docling_integration import process_with_docling
from shared.gemini_table_formatter import (
    extract_tables_from_docling_json,
    extract_text_content_from_docling,
    format_tables_with_gemini,
    merge_content_with_formatted_tables,
    process_docling_content
)
from shared.hybrid_content_processor import process_html_hybrid
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
        1. RESOLVE: Look up Gemini FileSearch store and user role (fail-fast approach)
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
            # Look up critical dependencies BEFORE starting crawl (fail-fast approach).
            # If FileSearch store doesn't exist, we want to know immediately rather than
            # after crawling 100 pages.

            logger.info(f"🚀 [SCRAPING] Starting website processing: {request.website_id}")
            logger.info(f"   URL: {request.url}")
            logger.info(f"   Depth: {request.crawl_config.max_depth}, Max Pages: {request.crawl_config.max_pages}")

            # Resolve Gemini FileSearch store name (used for all page uploads)
            # Raises exception if store doesn't exist - prevents wasted crawling
            store_name = await self._resolveFileSearchStore()

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
                store_name=store_name,
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
                job_context=job_context
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
            job_context: JobContext
        ) -> int:
            """Stream each page: crawl → process → upload → record. Return page count only."""
            pages_uploaded = 0
            start_time = time.time()

            logger.info(f"📄 [PIPELINE] Starting page-by-page streaming...")

            async for page_data in self._crawlPagesWithBFS(crawl_config, job_context):
                metrics = await self._processPageInPipeline(page_data, job_context, crawl_config)
                if metrics:
                    pages_uploaded += 1

            if pages_uploaded == 0:
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
            """Process one page: convert (docling) → upload → record"""
            logger.info(f"📄 [PIPELINE] Processing: {page_data.page_url}")

            try:
                start_time = time.time()

                # Convert HTML to markdown via docling
                # HTML is pre-cleaned by crawl4ai (menus, navbars, ads removed)
                try:
                    markdown_content, processed_content_s3_key = await self._preparePageAsMarkdown(
                        page_data.page_html, page_data.page_url, remove_ads=True
                    )
                except Exception as docling_error:
                    logger.error(f"   ❌ Docling processing failed: {docling_error}")
                    logger.warning(f"   ⏭️ Skipping page due to docling error")
                    return None

                page_data = PageData(
                    page_url=page_data.page_url,
                    page_html=page_data.page_html,
                    markdown=markdown_content,
                    title=page_data.title,
                    description=page_data.description,
                    session_id=page_data.session_id
                )

                # Upload
                upload_result = await self._uploadPageToGemini(page_data, job_context)
                if not upload_result:
                    logger.warning(f"   ⚠️ Upload failed, skipping this page")
                    return None

                # Store current page data for MIME type detection
                self._current_page_data = page_data

                logger.info(f"   ✅ Uploaded to Gemini: {upload_result.document_name}")

                # Record
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
        job_context: JobContext
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

            result = await self._fetchPageHTML(current_url, semaphore, crawl_config.delay_between_requests)
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
        delay: float
    ) -> Optional[Tuple[str, str, Optional[str], Optional[str], Optional[str]]]:
        """
        Fetch single page via crawl4ai with HTML cleaning.

        Crawl4ai removes menus, navbars, ads via built-in cleaning options.
        Returns: (url, cleaned_html, title, description, session_id)
        """
        async with semaphore:
            try:
                from crawl4ai import AsyncWebCrawler
                async with AsyncWebCrawler() as crawler:
                    # Use crawl4ai with aggressive noise removal
                    # Remove overlays, unwanted elements, and forms to get clean content
                    logger.info(f"🔍 [CRAWL4AI] Fetching {page_url} with aggressive noise removal...")
                    result = await crawler.arun(
                        url=page_url,
                        timeout=30,
                        js_code=None,
                        remove_overlay_elements=True,  # Remove modals, overlays, popups
                        remove_unwanted_elements=True,  # Remove sidebars, ads, navigation noise
                        remove_forms=True               # Remove form elements (usually not content)
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

                    logger.warning(f"⚠️ Failed to fetch {page_url}")
                    return None
            except Exception as e:
                logger.error(f"❌ Error fetching {page_url}: {e}")
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

    async def _preparePageAsMarkdown(self, html_content: str, page_url: str, remove_ads: bool = True) -> Tuple[str, Optional[str]]:
        """
        Process HTML with docling queue (same as file worker).
        HTML is pre-cleaned by crawl4ai to remove menus, navbars, ads.
        Extracts: text + tables, with text-based equation reconstruction.

        Returns:
            Tuple of (markdown_content, processed_content_s3_key)
        """
        import hashlib

        logger.info(f"📄 [DOCLING_WEB] Processing page with docling: {page_url}")
        logger.info(f"📄 [DOCLING_WEB] HTML size before docling: {len(html_content)} bytes")

        # Create URL hash for file naming
        url_hash = hashlib.md5(page_url.encode()).hexdigest()[:12]

        # 1. Upload cleaned HTML to S3 temporarily
        html_filename = f"page_{url_hash}.html"
        logger.info(f"📤 [S3_HTML_UPLOAD] Uploading HTML to S3 ({len(html_content)} bytes)...")

        html_upload_success, html_s3_key = await s3_file_storage.upload_file(
            file_data=html_content.encode('utf-8'),
            original_filename=html_filename,
            file_type="web-worker-temp"  # Temporary storage
        )

        if not html_upload_success:
            logger.error(f"❌ [S3_HTML_UPLOAD] Failed to upload HTML to S3")
            raise Exception(f"Failed to upload HTML to S3 for {page_url}")

        logger.info(f"✅ [S3_HTML_UPLOAD] HTML uploaded: {html_s3_key}")

        # 2. Generate presigned URL for docling to access
        logger.info(f"🔗 [S3] Generating presigned URL for S3 object: {html_s3_key}")
        success, result = s3_file_storage.generate_presigned_url(html_s3_key, expiration=3600)
        if not success:
            logger.error(f"❌ [S3] Failed to generate presigned URL: {result}")
            # Cleanup temp HTML
            try:
                await s3_file_storage.delete_file(html_s3_key)
            except:
                pass
            raise Exception(f"Failed to generate presigned URL: {result}")

        presigned_url = result
        logger.info(f"✅ [S3] Generated presigned URL for {html_s3_key}")
        logger.info(f"🔍 [DEBUG] presigned_url type: {type(presigned_url)}")
        logger.info(f"🔍 [DEBUG] presigned_url length: {len(presigned_url) if presigned_url else 'None'}")
        logger.info(f"🔍 [DEBUG] presigned_url starts with http: {presigned_url.startswith('http') if presigned_url else 'None'}")

        # 3. Call docling queue (same pattern as file worker)
        try:
            logger.info(f"🔍 [DEBUG] About to call process_with_docling with presigned_url: {presigned_url}")
            json_content, docling_metadata = await process_with_docling(
                presigned_url=presigned_url,
                original_filename=html_filename,
                mime_type="text/html"
            )
            logger.info(f"🔍 [DEBUG] process_with_docling returned: json_content={bool(json_content)}, metadata_keys={list(docling_metadata.keys()) if docling_metadata else 'None'}")

            logger.info(f"✅ [DOCLING_RESPONSE] Received docling JSON: {len(json_content)} chars")

            # Validate json_content is not empty
            if not json_content or len(json_content) == 0:
                logger.error(f"❌ [DOCLING_ERROR] json_content is empty!")
                raise Exception("Docling returned empty JSON")

            # Log comprehensive docling JSON structure (same as file worker)
            try:
                import json as json_lib
                parsed = json_lib.loads(json_content) if isinstance(json_content, str) and json_content.strip().startswith(('{', '[')) else None
                if parsed and isinstance(parsed, dict):
                    logger.info(f"📊 [DOCLING_STRUCTURE] Top-level keys: {list(parsed.keys())}")
                    # Log texts, tables, groups structure
                    texts_count = len(parsed.get('texts', []))
                    tables_list = parsed.get('tables', [])
                    tables_count = len(tables_list) if tables_list else 0
                    groups_count = len(parsed.get('groups', []))
                    body_children = parsed.get('body', {}).get('children', [])

                    logger.info(f"📊 [DOCLING_STRUCTURE] Content summary:")
                    logger.info(f"   texts: {texts_count}")
                    logger.info(f"   tables: {tables_count}")
                    logger.info(f"   groups: {groups_count}")
                    logger.info(f"   body.children: {len(body_children)}")

                    # Log text labels distribution for debugging
                    if parsed.get('texts'):
                        label_counts = {}
                        for text in parsed['texts']:
                            label = text.get('label', 'text')
                            label_counts[label] = label_counts.get(label, 0) + 1
                        logger.info(f"📊 [DOCLING_TEXT_LABELS] Distribution: {label_counts}")
                else:
                    logger.warning(f"⚠️ [DOCLING_STRUCTURE] Not valid JSON. First 500 chars: {repr(json_content[:500])}")
            except Exception as parse_err:
                logger.warning(f"⚠️ [DOCLING_STRUCTURE] Failed to parse: {parse_err}. First 500 chars: {repr(json_content[:500])}")

            # Use hybrid processing: trafilatura for text + docling for tables
            # This ensures clean article text is extracted while preserving table intelligence
            logger.info(f"🔄 [HYBRID_PROCESS] Using hybrid processing (trafilatura + docling)...")
            markdown_content = await process_html_hybrid(html_content, json_content)

            # 7. Upload final markdown to S3 (for download endpoint)
            md_filename = f"page_{url_hash}.md"
            md_success, md_s3_key = await s3_file_storage.upload_file(
                file_data=markdown_content.encode('utf-8'),
                original_filename=md_filename,
                file_type="processed"
            )

            processed_content_s3_key = md_s3_key if md_success else None
            logger.info(f"✅ [S3_MD_UPLOAD] Processed markdown uploaded: {processed_content_s3_key}")

            # 9. Cleanup temporary HTML from S3
            try:
                await s3_file_storage.delete_file(html_s3_key)
                logger.info(f"🗑️ [CLEANUP] Deleted temporary HTML: {html_s3_key}")
            except Exception as cleanup_err:
                logger.warning(f"⚠️ [CLEANUP] Failed to delete temp HTML: {cleanup_err}")

            return markdown_content, processed_content_s3_key

        except Exception as docling_err:
            logger.error(f"❌ [DOCLING_ERROR] Docling processing failed: {docling_err}")

            # Cleanup temp HTML
            try:
                await s3_file_storage.delete_file(html_s3_key)
            except:
                pass

            # Re-raise error - no fallback to trafilatura
            raise Exception(f"Docling processing failed for {page_url}: {docling_err}")

    async def _extractDocumentsFromPage(
        self, html_content: str, page_url: str, page_markdown: str
    ) -> str:
        """Extract embedded files from HTML if docling enabled"""
        from core.config import settings

        if not settings.docling_enabled:
            return page_markdown

        try:
            file_links = await self._findDocumentLinksInHTML(html_content, page_url)
            if not file_links:
                return page_markdown

            extracted_docs = await self._processEmbeddedDocuments(file_links)
            return await self._appendDocumentsToMarkdown(page_markdown, extracted_docs)
        except Exception as e:
            logger.warning(f"⚠️ [DOCLING] Error: {e}")
            return page_markdown

    async def _findDocumentLinksInHTML(self, html_content: str, page_url: str) -> List[Dict]:
        """Find embedded files (PDF, DOCX, etc.) in HTML"""
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, 'lxml')
        docling_supported = {'.pdf', '.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.xls'}

        file_links = []
        for link in soup.find_all('a', href=True):
            href = link['href']
            if not href.startswith(('http://', 'https://')):
                href = urljoin(page_url, href)

            if any(urlparse(href).path.lower().endswith(ext) for ext in docling_supported):
                file_links.append({'url': href, 'text': link.get_text(strip=True) or 'Document'})

        logger.info(f"📎 [DOCLING] Found {len(file_links)} embedded files")
        return file_links[:5]

    async def _processEmbeddedDocuments(self, file_links: List[Dict]) -> List[Dict]:
        """Process all files through docling service"""
        import httpx

        extracted_docs = []
        async with httpx.AsyncClient(timeout=60) as client:
            for file_link in file_links:
                doc = await self._processEmbeddedDocument(client, file_link)
                if doc:
                    extracted_docs.append(doc)

        return extracted_docs

    async def _processEmbeddedDocument(self, client: Any, file_link: Dict) -> Optional[Dict]:
        """Process single file through docling"""
        file_url = file_link['url']

        try:
            response = await client.get(file_url, timeout=30)
            if response.status_code != 200:
                logger.warning(f"⚠️ Failed to download {file_url}")
                return None

            if len(response.content) > 25 * 1024 * 1024:
                logger.warning(f"⚠️ File too large: {file_url}")
                return None

            return await self._downloadAndDoclingProcess(response.content, file_url, file_link)
        except Exception as e:
            logger.warning(f"⚠️ Error processing {file_url}: {e}")
            return None

    async def _downloadAndDoclingProcess(self, file_bytes: bytes, file_url: str, file_link: Dict) -> Optional[Dict]:
        """Save file and process through docling"""
        _, file_ext = os.path.splitext(urlparse(file_url).path.lower())
        fd, temp_path = tempfile.mkstemp(suffix=file_ext)

        try:
            os.write(fd, file_bytes)
            os.close(fd)

            from shared.docling_integration import process_with_docling

            mime_types = {
                '.pdf': 'application/pdf',
                '.docx': 'application/vnd.openxmlformats-officedocument.wordprocessingml.document',
                '.doc': 'application/msword',
                '.pptx': 'application/vnd.openxmlformats-officedocument.presentationml.presentation',
                '.ppt': 'application/vnd.ms-powerpoint',
                '.xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                '.xls': 'application/vnd.ms-excel',
            }

            filename = os.path.basename(urlparse(file_url).path)
            mime_type = mime_types.get(file_ext, 'application/octet-stream')

            markdown_content, _ = await process_with_docling(
                file_path=temp_path, 
                filename=filename, 
                mime_type=mime_type, 
                timeout_seconds=30,
                presigned_url=None  # Web worker uses local files
            )

            if markdown_content:
                logger.info(f"✅ [DOCLING] Extracted {len(markdown_content)} chars")
                return {'title': file_link['text'], 'filename': filename, 'content': markdown_content}

            return None
        finally:
            if os.path.exists(temp_path):
                os.unlink(temp_path)

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

    # ==================== UPLOAD LAYER ====================

    async def _resolveFileSearchStore(self) -> str:
        """Resolve FileSearch store name (fail fast)"""
        from core.config import settings
        from core.ai import get_genai_client

        store_display_name = settings.gemini_file_search_store_name
        if not store_display_name:
            raise Exception("GEMINI_FILE_SEARCH_STORE_NAME not configured")

        genai_client = get_genai_client()
        if not genai_client:
            raise Exception("Gemini client not configured")

        store = get_file_search_store_by_display_name(genai_client, display_name=store_display_name)
        if not store:
            raise Exception("FileSearch store not found")

        logger.info(f"✅ Resolved FileSearch store: {store}")
        return store

    async def _resolveUserRoleID(self, user_email: str, user_role_id: int = None) -> Optional[int]:
        """Resolve user_role_id (allow NULL if not found)"""
        if user_role_id:
            logger.info(f"✅ Using provided user_role_id: {user_role_id}")
            return user_role_id

        user_role_id = await self.scraping_dao.get_admin_user_role_id(user_email)
        if not user_role_id:
            logger.warning(f"⚠️ No user role found, will use NULL")

        return user_role_id

    async def _uploadPageToGemini(
        self,
        page_data: PageData,
        job_context: JobContext
    ) -> Optional[UploadResult]:
        """Upload single page to Gemini FileSearch"""
        from core.ai import get_genai_client
        import json
        
        # Use async client for consistency with polling method
        genai_client = get_genai_client().aio
        if not genai_client:
            raise Exception("Gemini client not configured")
        
        # Use markdown content for Gemini FileStore
        content = page_data.markdown
        mime_type = 'text/markdown'
        temp_suffix = '.md'
        logger.info(f"📋 [MARKDOWN_UPLOAD] Using markdown content for Gemini FileStore: {len(content)} chars")
        
        # Create temporary file with appropriate suffix
        fd, temp_file = tempfile.mkstemp(suffix=temp_suffix)
        try:
            os.write(fd, content.encode('utf-8'))
            os.close(fd)
            
            metrics = calculate_metrics(content)
            doc_name = f"page_{job_context.website_id}_{int(time.time())}"
            logger.info(f"   📤 Uploading: {doc_name} ({metrics.get('file_size_bytes', 0):,} bytes)")
            
            operation = await genai_client.file_search_stores.upload_to_file_search_store(
                file=temp_file,
                file_search_store_name=job_context.store_name,
                config=await self._buildGeminiUploadConfig(doc_name, job_context.website_id, page_data.page_url)
            )
            
            if not operation:
                logger.error(f"   ❌ Failed to create upload operation")
                return None
            
            return await self._waitForGeminiUploadCompletion(operation, job_context)
        finally:
            try:
                os.unlink(temp_file)
            except:
                pass
            await self._deleteTemporaryFile(temp_file)

    async def _buildGeminiUploadConfig(self, doc_name: str, website_id: int, page_url: str) -> Dict:
        """Build Gemini upload configuration for markdown content"""
        return {
            'display_name': doc_name,
            'mime_type': 'text/markdown',
            'custom_metadata': [
                {'key': 'source_type', 'string_value': 'website'},
                {'key': 'website_id', 'string_value': str(website_id)},
                {'key': 'page_url', 'string_value': page_url},
                {'key': 'content_format', 'string_value': 'markdown'}
            ]
        }

    async def _waitForGeminiUploadCompletion(self, operation, job_context: JobContext) -> Optional[UploadResult]:
        """Poll Gemini upload operation until done using async client"""
        from core.ai import get_genai_client

        # 1. Initialize the ASYNC client
        genai_client = get_genai_client().aio
        
        start_time = time.time()
        max_wait = 120  # Reduced from 300s to 120s (2 minutes)
        
        logger.info(f"   ⏳ Waiting for upload... (timeout: {max_wait}s)")
        
        # Keep track of the current operation object
        current_operation = operation
        
        while True:
            elapsed = time.time() - start_time
            if elapsed > max_wait:
                logger.error(f"   ❌ Timeout uploading ({elapsed:.0f}s)")
                return None
            
            logger.info(f"   ⏳ Waiting for upload... ({elapsed:.0f}s)")
            
            # Check if operation is done
            try:
                if getattr(current_operation, 'done', False):
                    logger.info(f"   ✅ Upload completed after {elapsed:.0f}s")
                    break
            except AttributeError as e:
                logger.warning(f"   ⚠️ Error checking operation.done: {e}")
            
            await asyncio.sleep(2)
            
            # Refresh operation status
            try:
                current_operation = await genai_client.operations.get(current_operation)
            except Exception as e:
                logger.warning(f"   ⚠️ Error refreshing operation status: {e}")
                # If we can't refresh, assume it's done after some time
                if elapsed > 30:
                    logger.info(f"   ℹ️ Assuming operation completed after {elapsed:.0f}s due to API errors")
                    break
                continue
        
        return await self._extractDocumentNameFromOperation(current_operation, job_context.store_name)

    async def _extractDocumentNameFromOperation(self, operation, store_name: str) -> Optional[UploadResult]:
        """Extract document name and URI from operation"""
        # Handle case where operation is still a string (ID)
        if isinstance(operation, str):
            logger.error(f"   ❌ Cannot extract document name from string operation: {operation}")
            return None
        
        # FileSearch upload returns result in response.document_name
        if hasattr(operation, 'response') and hasattr(operation.response, 'document_name'):
            doc_name = operation.response.document_name
            # Try to get URI if available
            doc_uri = getattr(operation.response, 'uri', None) if hasattr(operation.response, 'uri') else None
            
            logger.info(f"   ✅ FileSearch document: {doc_name}")
            if doc_uri:
                logger.info(f"   📎 Document URI: {doc_uri}")
            
            return UploadResult(
                document_name=doc_name,
                file_search_store_name=store_name,
                uploaded_at=datetime.utcnow(),
                gemini_file_uri=doc_uri
            )
        
        logger.error(f"   ❌ Upload failed or invalid response - no document_name in operation.response")
        return None

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
            processed_content_s3_key: str = None
        ) -> Optional[int]:
            """Record single page in database"""
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
                    processed_content_s3_key=processed_content_s3_key
                )

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
                    processed_content_s3_key=processed_content_s3_key
                )

                return job_context.website_id

            # This is a child page - record it as such
            child_page_id = await self.scraping_dao.record_child_page(
                parent_id=job_context.website_id,
                page_url=page_data.page_url,
                gemini_file_name=upload_result.document_name,
                gemini_file_uri=upload_result.gemini_file_uri,
                file_search_metadata=upload_result.file_search_metadata,
                user_role_id=job_context.user_role_id,
                file_size=calculate_metrics(page_data.markdown).get('file_size_bytes', 0),
                char_count=calculate_metrics(page_data.markdown).get('char_count', 0),
                title=page_data.title,
                description=page_data.description,
                crawl_session_id=page_data.session_id,
                processed_content_s3_key=processed_content_s3_key
            )

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
        website_id: int,
        page_data: PageData,
        upload_result: UploadResult,
        file_size: int,
        char_count: int,
        mark_completed: bool = True,
        processed_content_s3_key: str = None
    ) -> bool:
        """Update parent website record with single page data"""
        logger.info(f"💾 [UPDATE_WEBSITE] Updating website {website_id} with page data")

        return await self.scraping_dao.update_website_with_page_data(
            website_id=website_id,
            gemini_file_name=upload_result.document_name,
            gemini_file_uri=upload_result.gemini_file_uri,
            file_size=file_size,
            char_count=char_count,
            title=page_data.title,
            description=page_data.description,
            crawl_session_id=page_data.session_id,
            file_search_metadata=upload_result.file_search_metadata,
            mark_completed=mark_completed,
            processed_content_s3_key=processed_content_s3_key
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
