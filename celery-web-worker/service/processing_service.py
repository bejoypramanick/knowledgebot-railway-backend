"""
Website Processing Service for Celery Web Worker
Handles all website scraping, content extraction, and Gemini FileSearch upload
"""
import asyncio
import time
import os
import tempfile
from datetime import datetime
from typing import Dict, List, Any, Optional
import logging
from urllib.parse import urljoin, urlparse

from shared.otel_logger import get_otel_logger
from shared.file_search import get_file_search_store_by_display_name
from shared.file_metrics import calculate_metrics

logger = get_otel_logger("processing_service", "celery-web-worker")


class ProcessingService:
    """Handle website scraping and content processing"""

    def __init__(self):
        from dao.scraping_dao import ScrapingDAO
        self.scraping_dao = ScrapingDAO()

    async def process_website_content(
        self,
        website_id: int,
        url: str,
        max_depth: int = 2,
        max_pages: int = 100,
        max_concurrent: int = 10,
        delay_between_requests: float = 0.0,
        replace_existing: bool = False,
        user_email: str = "admin",
        user_role_id: int = None,
        celery_task_id: str = None,
        **options
    ) -> Dict[str, Any]:
        """
        Main orchestration function for website processing:
        1. Scrape website content
        2. Extract HTML content to Markdown
        3. Upload to Gemini FileSearch
        4. Record metadata in database

        Args:
            website_id: Database ID of website record
            url: Website URL to scrape
            max_depth: Maximum depth for crawling
            max_pages: Maximum number of pages to scrape
            max_concurrent: Maximum concurrent requests
            delay_between_requests: Delay between requests in seconds
            replace_existing: Whether to replace existing content
            user_email: User email for metadata
            celery_task_id: Celery task ID for cancellation checking
            **options: Additional scraping options

        Returns:
            Dictionary with success status and details
        """
        start_time = time.time()

        try:
            logger.info(f"🚀 [SCRAPING] Starting website processing: {website_id}")
            logger.info(f"   URL: {url}")
            logger.info(f"   Depth: {max_depth}, Max Pages: {max_pages}")
            logger.info(f"   Concurrent: {max_concurrent}, Delay: {delay_between_requests}s")

            # Step 1: Check for cancellation before starting
            if await self._is_task_cancelled(celery_task_id):
                logger.warning(f"❌ Task {celery_task_id} marked for cancellation")
                return {
                    "success": False,
                    "error": "Task cancelled by admin",
                    "website_id": website_id
                }

            # Step 2: Scrape website and collect pages
            logger.info(f"📄 [SCRAPING] Fetching pages from {url}")
            scraped_pages = await self._scrape_website(
                url=url,
                max_depth=max_depth,
                max_pages=max_pages,
                max_concurrent=max_concurrent,
                delay_between_requests=delay_between_requests,
                celery_task_id=celery_task_id
            )

            if not scraped_pages:
                logger.error(f"❌ Failed to scrape website: {url}")
                return {
                    "success": False,
                    "error": "No pages scraped from website",
                    "website_id": website_id
                }

            logger.info(f"✅ Scraped {len(scraped_pages)} pages from {url}")

            # Step 3: Extract and convert content for each page
            logger.info(f"🔄 [PROCESSING] Converting {len(scraped_pages)} pages to Markdown")
            processed_pages = []
            for page_url, page_html in scraped_pages:
                try:
                    markdown_content = await self._html_to_markdown(page_html)

                    # If docling is enabled, also extract embedded files from the page
                    markdown_content = await self._extract_embedded_files_if_docling_enabled(
                        page_html,
                        page_url,
                        markdown_content
                    )

                    processed_pages.append({
                        "url": page_url,
                        "markdown": markdown_content,
                        "html": page_html
                    })
                except Exception as e:
                    logger.warning(f"⚠️ Failed to process page {page_url}: {e}")
                    continue

            if not processed_pages:
                logger.error(f"❌ Failed to process any pages from {url}")
                return {
                    "success": False,
                    "error": "No pages successfully processed",
                    "website_id": website_id
                }

            logger.info(f"✅ Successfully processed {len(processed_pages)} pages")

            # Step 4: Upload to Gemini FileSearch
            logger.info(f"🤖 [GEMINI] Uploading {len(processed_pages)} pages to FileSearch")
            file_search_result = await self._upload_to_gemini(
                website_id=website_id,
                url=url,
                processed_pages=processed_pages,
                user_email=user_email,
                user_role_id=user_role_id,
                celery_task_id=celery_task_id
            )

            if not file_search_result.get("success"):
                logger.error(f"❌ Failed to upload to Gemini: {file_search_result.get('error')}")
                return {
                    "success": False,
                    "error": f"Gemini upload failed: {file_search_result.get('error')}",
                    "website_id": website_id
                }

            logger.info(f"✅ Successfully uploaded to Gemini FileSearch")

            # Step 5: Record metadata in database
            logger.info(f"💾 [DATABASE] Recording website metadata")
            db_result = await self._record_website_metadata(
                website_id=website_id,
                url=url,
                gemini_file_name=file_search_result.get("gemini_file_name"),
                file_search_metadata=file_search_result.get("file_search_metadata"),
                page_count=len(processed_pages),
                user_email=user_email
            )

            if not db_result.get("success"):
                logger.error(f"❌ Failed to record metadata: {db_result.get('error')}")
                return {
                    "success": False,
                    "error": f"Database recording failed: {db_result.get('error')}",
                    "website_id": website_id
                }

            processing_time = time.time() - start_time

            logger.info(f"✅ [COMPLETE] Website {website_id} processed successfully")
            logger.info(f"   Pages: {len(processed_pages)}")
            logger.info(f"   Time: {processing_time:.1f}s")

            # SUCCESS: Publish result to Redis
            result = {
                "success": True,
                "message": f"Website processed successfully: {len(processed_pages)} pages",
                "website_id": website_id,
                "page_count": len(processed_pages),
                "processing_time_seconds": processing_time,
                "gemini_file_name": file_search_result.get("gemini_file_name"),
                "file_search_metadata": file_search_result.get("file_search_metadata")
            }

            try:
                from shared.redis_message_queue import redis_message_queue
                redis_message_queue.publish_web_result(
                    website_id=website_id,
                    celery_task_id=celery_task_id,
                    status="completed",
                    result=result
                )
            except Exception as redis_error:
                logger.warning(f"⚠️ Failed to publish result to Redis: {redis_error}")

            return result

        except Exception as e:
            logger.error(f"❌ Unexpected error processing website {website_id}: {e}")

            # FAILURE: Publish error result to Redis
            try:
                from shared.redis_message_queue import redis_message_queue
                redis_message_queue.publish_web_result(
                    website_id=website_id,
                    celery_task_id=celery_task_id,
                    status="failed",
                    error=str(e)
                )
            except Exception as redis_error:
                logger.warning(f"⚠️ Failed to publish error to Redis: {redis_error}")

            return {
                "success": False,
                "error": f"Processing error: {str(e)}",
                "website_id": website_id
            }

    async def _is_task_cancelled(self, celery_task_id: str) -> bool:
        """Check if task has been marked for cancellation via Redis"""
        if not celery_task_id:
            return False

        try:
            import redis as redis_lib
            # Use WEB_REDIS_URL (DB 1) for web tasks
            redis_url = os.getenv('WEB_REDIS_URL', 'redis://localhost:6379/1')

            try:
                redis_conn = redis_lib.from_url(redis_url, socket_connect_timeout=2)
                cancelled_key = f"task_cancelled:{celery_task_id}"
                result = redis_conn.exists(cancelled_key)
                redis_conn.close()
                return bool(result)
            except redis_lib.ConnectionError as conn_err:
                # Redis not available - not critical, just skip cancellation check
                # This is common in local development without Redis
                logger.debug(f"ℹ️ Redis unavailable for cancellation check (this is OK): {redis_url}")
                return False
        except Exception as e:
            logger.debug(f"ℹ️ Skipping cancellation check: {e}")
            return False

    async def _scrape_website(
        self,
        url: str,
        max_depth: int,
        max_pages: int,
        max_concurrent: int,
        delay_between_requests: float,
        celery_task_id: str = None
    ) -> List[tuple]:
        """
        Scrape website using crawl4ai with concurrency control

        Returns:
            List of tuples: [(page_url, page_html), ...]
        """
        try:
            # Check if dependencies are available
            try:
                from crawl4ai import AsyncWebCrawler, CrawlResult
                logger.info("✅ crawl4ai is available")
            except ImportError as ie:
                logger.error(f"❌ crawl4ai not available: {ie}")
                logger.error("   Make sure: pip install crawl4ai")
                logger.error("   And run: playwright install")
                return []

            pages = []
            visited_urls = set()
            to_visit = [(url, 0)]  # (url, depth)
            semaphore = asyncio.Semaphore(max_concurrent)

            logger.info(f"🔄 Starting BFS crawl with max_depth={max_depth}, max_pages={max_pages}")

            async def fetch_page(page_url: str) -> Optional[tuple]:
                """Fetch a single page with semaphore limiting"""
                # Check cancellation periodically
                if await self._is_task_cancelled(celery_task_id):
                    logger.warning(f"⏸️ Crawling cancelled for {url}")
                    return None

                async with semaphore:
                    try:
                        logger.info(f"📄 Fetching: {page_url}")

                        try:
                            async with AsyncWebCrawler() as crawler:
                                result: CrawlResult = await crawler.arun(
                                    url=page_url,
                                    timeout=30,
                                    js_code=None  # Set to JavaScript code if needed for dynamic content
                                )

                                if result.success and result.html:
                                    logger.info(f"✅ Fetched {len(result.html)} bytes from {page_url}")

                                    # Apply delay before next request
                                    if delay_between_requests > 0:
                                        await asyncio.sleep(delay_between_requests)

                                    return (page_url, result.html)
                                else:
                                    # Log detailed error info from crawler
                                    error_msg = getattr(result, 'error_message', 'Unknown error')
                                    logger.warning(f"⚠️ Failed to fetch {page_url}: {error_msg}")
                                    logger.warning(f"   Success: {result.success}, HTML length: {len(result.html) if result.html else 0}")
                                    return None
                        except ImportError as ie:
                            logger.error(f"❌ Import error - crawl4ai or dependencies not available: {ie}")
                            logger.error(f"   Make sure crawl4ai is installed and playwright browsers are available")
                            return None

                    except Exception as e:
                        logger.error(f"❌ Error fetching {page_url}: {e}")
                        import traceback
                        logger.error(f"   Traceback: {traceback.format_exc()}")
                        return None

            # BFS crawling with depth control
            logger.info(f"📋 [BFS] Starting queue with: {to_visit}")
            while to_visit and len(pages) < max_pages:
                current_url, current_depth = to_visit.pop(0)
                normalized_current_url = self._normalize_url(current_url)
                logger.info(f"📋 [BFS] Processing queue item: {current_url} (normalized: {normalized_current_url}, depth={current_depth}, visited={len(visited_urls)}, pages={len(pages)})")

                # Skip if already visited or depth exceeded
                if normalized_current_url in visited_urls:
                    logger.info(f"⏭️  [BFS] Already visited: {current_url} (normalized: {normalized_current_url})")
                    continue
                if current_depth > max_depth:
                    logger.info(f"⏭️  [BFS] Depth exceeded ({current_depth} > {max_depth}): {current_url}")
                    continue

                visited_urls.add(normalized_current_url)

                # Fetch page
                logger.info(f"🔍 [BFS] Fetching page at depth {current_depth}: {current_url}")
                result = await fetch_page(current_url)
                if result:
                    pages.append(result)
                    logger.info(f"✅ [BFS] Added page {len(pages)}/{max_pages}")
                    page_url, page_html = result

                    # Extract links for next level if depth allows
                    if current_depth < max_depth and len(pages) < max_pages:
                        try:
                            from bs4 import BeautifulSoup

                            soup = BeautifulSoup(page_html, 'lxml')
                            base_domain = self._get_domain(url)
                            logger.info(f"🔗 [LINKS] Extracting links from {current_url} (base_domain={base_domain})")

                            found_links = []
                            all_links = soup.find_all('a', href=True)
                            logger.info(f"🔗 [LINKS] Found {len(all_links)} total <a> tags")

                            for link in all_links:
                                href = link['href']
                                # Convert relative URLs to absolute
                                if href.startswith('/'):
                                    href = f"{base_domain}{href}"
                                elif not href.startswith('http'):
                                    continue

                                # Normalize URL for deduplication
                                normalized_href = self._normalize_url(href)

                                # Only crawl same domain
                                if self._get_domain(href) == base_domain and normalized_href not in visited_urls:
                                    to_visit.append((href, current_depth + 1))
                                    found_links.append(href)
                                    logger.debug(f"🔗 [LINKS] Queued (normalized): {normalized_href}")
                                    if len(pages) >= max_pages:
                                        break

                            logger.info(f"🔗 [LINKS] Added {len(found_links)} new links to queue")

                        except Exception as e:
                            logger.warning(f"⚠️ Failed to extract links from {current_url}: {e}")
                            import traceback
                            logger.warning(f"   Traceback: {traceback.format_exc()}")

            logger.info(f"✅ Crawling complete: {len(pages)} pages collected")
            return pages

        except Exception as e:
            logger.error(f"❌ Website scraping failed: {e}")
            return []

    async def _html_to_markdown(self, html_content: str) -> str:
        """Convert HTML content to Markdown with noise filtering"""
        try:
            import trafilatura
            from markdownify import markdownify as md
            from bs4 import BeautifulSoup

            # Step 1: Use trafilatura to extract main content (removes boilerplate, ads, nav, etc)
            logger.info("🧹 [CONTENT_EXTRACTION] Using trafilatura to extract main content...")
            extracted_content = trafilatura.extract(html_content, include_comments=False)

            if extracted_content:
                logger.info("✅ [TRAFILATURA] Successfully extracted main content")
                # Convert extracted content to markdown
                markdown = md(extracted_content, heading_style="atx")
            else:
                logger.warning("⚠️ [TRAFILATURA] Failed to extract content, falling back to manual cleaning")
                # Fallback: Manual HTML cleaning
                soup = BeautifulSoup(html_content, 'lxml')
                # Remove script, style, nav, footer, header, aside, and other noise elements
                for element in soup(["script", "style", "nav", "footer", "header", "aside",
                                     "form", "button", "meta", "link", "noscript"]):
                    element.extract()

                # Remove elements with common ad/nav class names
                for element in soup.find_all(class_=lambda x: x and any(
                    noise in x.lower() for noise in ['ad', 'sidebar', 'widget', 'comment', 'related', 'cookie'])):
                    element.extract()

                # Convert to markdown
                markdown = md(str(soup), heading_style="atx")

            # Step 2: Clean up markdown formatting
            logger.info("🧹 [MARKDOWN_CLEANUP] Cleaning up markdown formatting...")
            lines = markdown.split('\n')
            lines = [line.rstrip() for line in lines]
            lines = [line for line in lines if line.strip()]  # Remove empty lines

            # Remove lines that are just special characters or very short noise
            lines = [line for line in lines if len(line) > 2 or line.startswith('#')]

            markdown = '\n'.join(lines)

            # Remove excessive blank lines (more than 2 consecutive)
            while '\n\n\n' in markdown:
                markdown = markdown.replace('\n\n\n', '\n\n')

            logger.info(f"✅ [CONTENT_EXTRACTED] Content cleaned: {len(markdown)} characters")
            return markdown

        except Exception as e:
            logger.error(f"❌ HTML to Markdown conversion failed: {e}")
            raise

    async def _extract_embedded_files_if_docling_enabled(
        self,
        html_content: str,
        page_url: str,
        page_markdown: str
    ) -> str:
        """
        Extract embedded files (PDF, DOCX, etc.) from HTML if docling is enabled.
        Process them through docling service and append to markdown.

        Only runs if DOCLING_ENABLED is true.
        """
        from core.config import settings

        # Only run if docling is enabled
        if not settings.docling_enabled:
            return page_markdown

        try:
            from bs4 import BeautifulSoup
            import httpx

            logger.info("📎 [DOCLING] Checking for embedded files since DOCLING_ENABLED=true")

            # Parse HTML to find file links
            soup = BeautifulSoup(html_content, 'lxml')
            docling_supported = {'.pdf', '.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.xls'}

            # Find all links to supported file types
            file_links = []
            for link in soup.find_all('a', href=True):
                href = link['href']
                # Skip if already absolute, make absolute
                if not href.startswith(('http://', 'https://')):
                    href = urljoin(page_url, href)

                # Check if it's a supported file type
                parsed_url = urlparse(href)
                path_lower = parsed_url.path.lower()

                if any(path_lower.endswith(ext) for ext in docling_supported):
                    file_links.append({
                        'url': href,
                        'text': link.get_text(strip=True) or 'Document'
                    })

            if not file_links:
                logger.info("📎 [DOCLING] No embedded files found in page")
                return page_markdown

            logger.info(f"📎 [DOCLING] Found {len(file_links)} embedded files in page")

            # Limit to max 5 files per page to avoid overwhelming processing
            max_files = 5
            if len(file_links) > max_files:
                logger.warning(f"⚠️ [DOCLING] Found {len(file_links)} files, limiting to {max_files}")
                file_links = file_links[:max_files]

            # Process each file through docling
            extracted_docs = []

            async with httpx.AsyncClient(timeout=60) as client:
                for i, file_link in enumerate(file_links, 1):
                    try:
                        file_url = file_link['url']
                        file_text = file_link['text']

                        logger.info(f"📥 [DOCLING] Downloading file {i}/{len(file_links)}: {file_url}")

                        # Download file with size limit (max 25MB per file)
                        response = await client.get(file_url, timeout=30)

                        if response.status_code != 200:
                            logger.warning(f"⚠️ [DOCLING] Failed to download {file_url}: HTTP {response.status_code}")
                            continue

                        file_size = len(response.content)
                        max_file_size = 25 * 1024 * 1024  # 25MB

                        if file_size > max_file_size:
                            logger.warning(f"⚠️ [DOCLING] File too large ({file_size/1024/1024:.1f}MB > 25MB): {file_url}")
                            continue

                        logger.info(f"📥 [DOCLING] Downloaded {file_size/1024:.1f}KB from {file_url}")

                        # Save to temporary file
                        _, file_ext = os.path.splitext(urlparse(file_url).path.lower())
                        fd, temp_path = tempfile.mkstemp(suffix=file_ext)

                        try:
                            os.write(fd, response.content)
                            os.close(fd)

                            # Process through docling
                            from shared.docling_integration import process_with_docling

                            # Infer MIME type from extension
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

                            filename = os.path.basename(urlparse(file_url).path)

                            logger.info(f"🤖 [DOCLING] Processing {filename} through docling service...")

                            markdown_content, metadata = await process_with_docling(
                                temp_path,
                                filename,
                                mime_type,
                                timeout_seconds=30
                            )

                            if markdown_content:
                                logger.info(f"✅ [DOCLING] Successfully extracted {len(markdown_content)} chars from {filename}")
                                extracted_docs.append({
                                    'title': file_text,
                                    'filename': filename,
                                    'content': markdown_content
                                })
                            else:
                                logger.warning(f"⚠️ [DOCLING] Failed to extract content from {filename}")

                        finally:
                            if os.path.exists(temp_path):
                                os.unlink(temp_path)

                    except Exception as e:
                        logger.warning(f"⚠️ [DOCLING] Error processing {file_link['url']}: {e}")
                        continue

            # If we extracted any documents, append to markdown
            if extracted_docs:
                logger.info(f"✅ [DOCLING] Extracted {len(extracted_docs)} embedded files, appending to page markdown")

                page_markdown += "\n\n---\n\n## Embedded Documents\n\n"

                for doc in extracted_docs:
                    page_markdown += f"### {doc['title']}\n"
                    page_markdown += f"*Source: {doc['filename']}*\n\n"
                    page_markdown += doc['content']
                    page_markdown += "\n\n"

            return page_markdown

        except Exception as e:
            logger.warning(f"⚠️ [DOCLING] Error extracting embedded files: {e}")
            # Return original markdown if extraction fails
            return page_markdown

    async def _upload_to_gemini(
        self,
        website_id: int,
        url: str,
        processed_pages: List[Dict[str, str]],
        user_email: str,
        user_role_id: int = None,
        celery_task_id: str = None
    ) -> Dict[str, Any]:
        """Upload website content to Gemini FileSearch"""
        try:
            from core.ai import get_genai_client
            from core.config import settings
            import json
            import tempfile
            import os

            genai_client = get_genai_client()
            if not genai_client:
                raise Exception("Gemini client not configured")

            # Get FileSearch store
            store_display_name = settings.gemini_file_search_store_name
            if not store_display_name:
                raise Exception("GEMINI_FILE_SEARCH_STORE_NAME not configured")

            file_search_store_name = get_file_search_store_by_display_name(
                genai_client,
                display_name=store_display_name
            )

            if not file_search_store_name:
                logger.error("❌ FileSearch store not found")
                raise Exception("FileSearch store not found")

            logger.info(f"📤 Uploading {len(processed_pages)} pages individually to FileSearch")

            # Use user_role_id if provided, otherwise try to look up from database
            logger.info(f"👤 [UPLOAD_START] user_role_id value: {user_role_id} (type: {type(user_role_id).__name__})")
            if not user_role_id:
                logger.info(f"ℹ️ user_role_id not provided, attempting to look up for {user_email}...")
                user_role_id = await self.scraping_dao.get_admin_user_role_id(user_email)
                if not user_role_id:
                    logger.warning(f"⚠️ Could not find user role for {user_email}, child pages will have NULL user_role_id")
                else:
                    logger.info(f"✅ Looked up user_role_id from database: {user_role_id}")
            else:
                logger.info(f"✅ Using provided user_role_id: {user_role_id}")

            uploaded_pages = []
            failed_pages = []

            # Upload each page individually
            for idx, page in enumerate(processed_pages, 1):
                # CHECK FOR CANCELLATION BEFORE PROCESSING EACH PAGE
                if await self._is_task_cancelled(celery_task_id):
                    logger.warning(f"❌ Task cancelled before processing page {idx}/{len(processed_pages)}")
                    raise Exception("Task cancelled by admin")

                page_url = page['url']
                page_markdown = page['markdown']

                logger.info(f"📄 [{idx}/{len(processed_pages)}] Uploading page: {page_url}")

                try:
                    # Create temp file for this page
                    with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as pf:
                        pf.write(page_markdown)
                        page_temp_file = pf.name

                    try:
                        # Calculate metrics before upload
                        metrics = calculate_metrics(page_markdown)
                        char_count = metrics.get('char_count', 0)
                        file_size = metrics.get('file_size_bytes', 0)

                        # Upload this page to FileSearch
                        document_display_name = f"page_{website_id}_{int(time.time())}_{idx}"

                        logger.info(f"   - Document: {document_display_name}")
                        logger.info(f"   - Size: {file_size:,} bytes")
                        logger.info(f"   - Characters: {char_count:,}")

                        # Upload using async LRO pattern
                        operation = genai_client.file_search_stores.upload_to_file_search_store(
                            file=page_temp_file,
                            file_search_store_name=file_search_store_name,
                            config={
                                'display_name': document_display_name,
                                'mime_type': 'text/markdown',
                                'custom_metadata': [
                                    {'key': 'source_type', 'string_value': 'website'},
                                    {'key': 'website_id', 'string_value': str(website_id)},
                                    {'key': 'source_url', 'string_value': url},
                                    {'key': 'page_url', 'string_value': page_url}
                                ]
                            }
                        )

                        if not operation:
                            logger.error(f"   ❌ Failed to create upload operation for {page_url}")
                            failed_pages.append(page_url)
                            continue

                        # Wait for upload to complete
                        start_time = time.time()
                        max_wait_time = 300  # 5 minutes
                        document_name = None

                        while not operation.done:
                            # CHECK FOR CANCELLATION WHILE WAITING FOR UPLOAD
                            if await self._is_task_cancelled(celery_task_id):
                                logger.error(f"❌ TASK CANCELLED WHILE UPLOADING - STOPPING ENTIRE PROCESS")
                                raise Exception("Task cancelled by admin during upload")

                            elapsed = time.time() - start_time
                            if elapsed > max_wait_time:
                                logger.error(f"   ❌ Timeout uploading {page_url}")
                                failed_pages.append(page_url)
                                break

                            await asyncio.sleep(5)
                            operation = genai_client.operations.get(operation)

                        if operation.done and hasattr(operation, 'response') and hasattr(operation.response, 'document_name'):
                            document_name = operation.response.document_name
                            logger.info(f"   ✅ Created FileSearch document: {document_name}")

                            # CHECK FOR CANCELLATION AFTER UPLOAD, BEFORE RECORDING
                            if await self._is_task_cancelled(celery_task_id):
                                logger.error(f"❌ TASK CANCELLED AFTER UPLOAD - STOPPING ENTIRE PROCESS")
                                raise Exception("Task cancelled by admin after upload")

                            # Prepare metadata for this page
                            file_search_metadata = {
                                "type": "file_search",
                                "file_search_store_name": file_search_store_name,
                                "document_name": document_name,
                                "uploaded_at": datetime.utcnow().isoformat()
                            }

                            # Record this page in database IMMEDIATELY
                            child_page_id = await self.scraping_dao.record_child_page(
                                parent_id=website_id,
                                page_url=page_url,
                                gemini_file_name=document_name,
                                file_search_metadata=file_search_metadata,
                                user_role_id=user_role_id,
                                file_size=file_size,
                                char_count=char_count
                            )

                            if child_page_id:
                                logger.info(f"   ✅ Recorded child page ID: {child_page_id}")
                                uploaded_pages.append({
                                    "url": page_url,
                                    "page_id": child_page_id,
                                    "document_name": document_name,
                                    "metadata": file_search_metadata
                                })
                            else:
                                logger.error(f"   ❌ Failed to record child page in database")
                                failed_pages.append(page_url)
                        else:
                            logger.error(f"   ❌ FileSearch upload failed for {page_url}")
                            failed_pages.append(page_url)

                    finally:
                        # Clean up temp file
                        try:
                            os.unlink(page_temp_file)
                        except:
                            pass

                except Exception as page_error:
                    logger.error(f"   ❌ Error uploading page {page_url}: {page_error}")
                    failed_pages.append(page_url)
                    continue

            # Summary
            logger.info(f"\n📊 Upload Summary:")
            logger.info(f"   - Pages uploaded: {len(uploaded_pages)}/{len(processed_pages)}")
            logger.info(f"   - Failed: {len(failed_pages)}")

            if failed_pages:
                logger.warning(f"   - Failed pages: {', '.join(failed_pages)}")

            if not uploaded_pages:
                raise Exception(f"Failed to upload any pages. {len(failed_pages)} pages failed.")

            # Return success with all uploaded pages info
            return {
                "success": True,
                "pages_uploaded": len(uploaded_pages),
                "pages_failed": len(failed_pages),
                "uploaded_pages": uploaded_pages,
                "file_search_metadata": {
                    "type": "file_search",
                    "file_search_store_name": file_search_store_name,
                    "pages_count": len(uploaded_pages),
                    "uploaded_at": datetime.utcnow().isoformat()
                }
            }

        except Exception as e:
            import traceback
            logger.error(f"❌ Gemini upload failed: {type(e).__name__}: {e}")
            logger.error(f"   Traceback: {traceback.format_exc()}")
            return {
                "success": False,
                "error": str(e)
            }

    async def _record_website_metadata(
        self,
        website_id: int,
        url: str,
        gemini_file_name: str,
        file_search_metadata: Dict[str, Any],
        page_count: int,
        user_email: str
    ) -> Dict[str, Any]:
        """
        Record website metadata in database.
        With the new per-page upload approach, this updates the main website record
        with overall status and metadata about the pages_uploaded.
        Individual page records are created immediately during upload.
        """
        try:
            from shared.db import get_db_connection
            import json

            async with get_db_connection() as conn:
                # Update the main website record with overall status
                # Extract pages_uploaded count from file_search_metadata if available
                pages_uploaded = file_search_metadata.get('pages_count', page_count) if file_search_metadata else page_count

                await conn.execute(
                    """UPDATE scraped_websites
                       SET pages_scraped = $1,
                           metadata = $2,
                           processing_status = 'completed',
                           updated_at = NOW()
                       WHERE id = $3""",
                    pages_uploaded,
                    json.dumps(file_search_metadata),
                    website_id
                )

            logger.info(f"✅ Recorded metadata for website {website_id}")
            logger.info(f"   - Pages uploaded: {pages_uploaded}")
            logger.info(f"   - Status: completed")

            return {
                "success": True,
                "website_id": website_id,
                "page_count": pages_uploaded
            }

        except Exception as e:
            logger.error(f"❌ Failed to record metadata: {e}")
            return {
                "success": False,
                "error": str(e)
            }

    @staticmethod
    def _get_domain(url: str) -> str:
        """Extract domain from URL"""
        try:
            from urllib.parse import urlparse

            parsed = urlparse(url)
            domain = f"{parsed.scheme}://{parsed.netloc}"
            return domain
        except:
            return url

    @staticmethod
    def _normalize_url(url: str) -> str:
        """Normalize URL for consistent deduplication.

        Removes query parameters, fragments, and normalizes trailing slashes.
        This ensures that URLs like https://example.com/ and https://example.com
        are treated as the same page.
        """
        try:
            from urllib.parse import urlparse, urlunparse

            parsed = urlparse(url)

            # Remove query parameters and fragments (they're not relevant for crawling)
            normalized = urlunparse((
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                '',  # params (empty)
                '',  # query (empty)
                ''   # fragment (empty)
            ))

            # Remove trailing slash from path (but keep it for root: https://example.com/)
            if normalized.endswith('/') and not normalized.endswith('://'):
                # Check if path is not just the root
                if parsed.path not in ('/', ''):
                    normalized = normalized.rstrip('/')
            # Ensure root URLs always have trailing slash (https://example.com/)
            elif not normalized.endswith('/') and not parsed.path:
                normalized += '/'

            return normalized.lower()  # Lowercase for case-insensitive comparison
        except:
            return url.lower()
