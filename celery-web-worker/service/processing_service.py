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

from models.value_objects import (
    CrawlConfig,
    JobContext,
    PageData,
    UploadResult,
    PageMetrics,
    AggregateMetrics,
    ProcessingResult,
    FinalizeRequest,
)

logger = get_otel_logger("processing_service", "celery-web-worker")


class ProcessingService:
    """Handle website scraping and content processing with value objects"""

    def __init__(self):
        from dao.scraping_dao import ScrapingDAO
        self.scraping_dao = ScrapingDAO()

    # ==================== MAIN ORCHESTRATOR ====================

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
        """Main orchestration: resolve → stream → finalize → publish"""
        start_time = time.time()
        try:
            logger.info(f"🚀 [SCRAPING] Starting website processing: {website_id}")
            logger.info(f"   URL: {url}")
            logger.info(f"   Depth: {max_depth}, Max Pages: {max_pages}")

            # Build value objects
            crawl_config = CrawlConfig(
                max_depth=max_depth,
                max_pages=max_pages,
                max_concurrent=max_concurrent,
                delay_between_requests=delay_between_requests
            )

            store_name = await self._resolveFileSearchStore()
            resolved_user_role_id = await self._resolveUserRoleID(user_email, user_role_id)

            job_context = JobContext(
                website_id=website_id,
                root_url=url,
                celery_task_id=celery_task_id,
                store_name=store_name,
                user_role_id=resolved_user_role_id
            )

            # Process pages
            aggregate_metrics = await self._crawlWebsitePages(
                crawl_config=crawl_config,
                job_context=job_context
            )

            # Finalize
            finalize_request = FinalizeRequest(
                website_id=website_id,
                page_count=aggregate_metrics.total_pages_uploaded,
                total_size_bytes=aggregate_metrics.total_size_bytes,
                total_char_count=aggregate_metrics.total_char_count,
                file_search_store_name=store_name
            )
            await self._recordWebsiteToDB(finalize_request)

            # Build result
            processing_time = time.time() - start_time
            result = ProcessingResult(
                success=True,
                website_id=website_id,
                message=f"Website processed successfully: {aggregate_metrics.total_pages_uploaded} pages",
                page_count=aggregate_metrics.total_pages_uploaded,
                total_size_bytes=aggregate_metrics.total_size_bytes,
                total_char_count=aggregate_metrics.total_char_count,
                processing_time_seconds=processing_time
            )

            logger.info(f"✅ [COMPLETE] Website {website_id} processed: {aggregate_metrics.total_pages_uploaded} pages in {processing_time:.1f}s")

            # Publish
            await self._reportSuccessResult(result, job_context)
            return result.to_dict()

        except Exception as e:
            processing_time = time.time() - start_time
            result = ProcessingResult(
                success=False,
                website_id=website_id,
                message="Processing failed",
                page_count=0,
                total_size_bytes=0,
                total_char_count=0,
                processing_time_seconds=processing_time,
                error=str(e)
            )
            logger.error(f"❌ Processing error: {e}")
            await self._reportErrorResult(result, celery_task_id)
            return result.to_dict()

    async def _crawlWebsitePages(
        self,
        crawl_config: CrawlConfig,
        job_context: JobContext
    ) -> AggregateMetrics:
        """Stream each page: crawl → process → upload → record"""
        pages_uploaded = total_size = total_chars = 0
        start_time = time.time()

        logger.info(f"📄 [PIPELINE] Starting page-by-page streaming...")

        async for page_data in self._crawlPagesWithBFS(crawl_config, job_context):
            if await self._isTaskCancelled(job_context.celery_task_id):
                logger.warning(f"⏸️ Cancellation detected, stopping pipeline")
                break

            metrics = await self._processPageInPipeline(page_data, job_context)
            if metrics:
                pages_uploaded += 1
                total_size += metrics.file_size_bytes
                total_chars += metrics.char_count

        if pages_uploaded == 0:
            raise Exception("No pages successfully processed")

        total_time = time.time() - start_time
        logger.info(f"✅ [PIPELINE] Completed: {pages_uploaded} pages in {total_time:.1f}s")

        return AggregateMetrics(
            total_pages_uploaded=pages_uploaded,
            total_size_bytes=total_size,
            total_char_count=total_chars,
            total_time_seconds=total_time
        )

    async def _processPageInPipeline(
        self,
        page_data: PageData,
        job_context: JobContext
    ) -> Optional[PageMetrics]:
        """Process one page: convert → upload → record"""
        logger.info(f"📄 [PIPELINE] Processing: {page_data.page_url}")

        try:
            start_time = time.time()

            # Convert
            markdown = await self._preparePageAsMarkdown(page_data.page_html, page_data.page_url)
            page_data = PageData(
                page_url=page_data.page_url,
                page_html=page_data.page_html,
                markdown=markdown
            )

            # Upload
            upload_result = await self._uploadPageToGemini(page_data, job_context)
            if not upload_result:
                logger.warning(f"   ⚠️ Upload failed, skipping this page")
                return None

            logger.info(f"   ✅ Uploaded to Gemini: {upload_result.document_name}")

            # Record
            await self._recordPageToDB(page_data, upload_result, job_context)

            # Metrics
            metrics = calculate_metrics(markdown)
            processing_time = time.time() - start_time

            return PageMetrics(
                file_size_bytes=metrics.get('file_size_bytes', 0),
                char_count=metrics.get('char_count', 0),
                processing_time_seconds=processing_time
            )
        except Exception as e:
            logger.error(f"   ❌ Error: {e}")
            return None

    async def _reportSuccessResult(self, result: ProcessingResult, job_context: JobContext):
        """Publish success to Redis"""
        try:
            from shared.redis_message_queue import redis_message_queue
            redis_message_queue.publish_web_result(
                job_context.website_id,
                job_context.celery_task_id,
                "completed",
                result.to_dict()
            )
        except Exception as e:
            logger.warning(f"⚠️ Failed to publish result: {e}")

    async def _reportErrorResult(self, result: ProcessingResult, celery_task_id: str):
        """Publish error to Redis"""
        try:
            from shared.redis_message_queue import redis_message_queue
            redis_message_queue.publish_web_result(
                result.website_id,
                celery_task_id,
                "failed",
                error=result.error
            )
        except Exception as e:
            logger.warning(f"⚠️ Failed to publish error: {e}")

    # ==================== CRAWL LAYER ====================

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

        visited_urls = set()
        to_visit = [(job_context.root_url, 0)]
        semaphore = asyncio.Semaphore(crawl_config.max_concurrent)
        pages_yielded = 0

        logger.info(f"🔄 Starting BFS crawl with max_depth={crawl_config.max_depth}, max_pages={crawl_config.max_pages}")

        while to_visit and pages_yielded < crawl_config.max_pages:
            if await self._isTaskCancelled(job_context.celery_task_id):
                logger.warning(f"⏸️ Crawling cancelled")
                break

            current_url, current_depth = to_visit.pop(0)

            if not await self._validateURLForCrawl(current_url, current_depth, crawl_config.max_depth, visited_urls):
                continue

            visited_urls.add(self._normalize_url(current_url))

            result = await self._fetchPageHTML(current_url, semaphore, crawl_config.delay_between_requests)
            if result:
                page_url, page_html = result
                pages_yielded += 1
                logger.info(f"✅ [BFS] Yielded page {pages_yielded}/{crawl_config.max_pages}")

                yield PageData(page_url=page_url, page_html=page_html)

                if current_depth < crawl_config.max_depth and pages_yielded < crawl_config.max_pages:
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
    ) -> Optional[Tuple[str, str]]:
        """Fetch single page via crawl4ai"""
        async with semaphore:
            try:
                from crawl4ai import AsyncWebCrawler
                async with AsyncWebCrawler() as crawler:
                    result = await crawler.arun(url=page_url, timeout=30, js_code=None)

                    if result.success and result.html:
                        if delay > 0:
                            await asyncio.sleep(delay)
                        logger.info(f"✅ Fetched {len(result.html)} bytes from {page_url}")
                        return (page_url, result.html)

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

    # ==================== CONTENT LAYER ====================

    async def _preparePageAsMarkdown(self, html: str, page_url: str) -> str:
        """Convert HTML to Markdown and extract embedded files"""
        markdown = await self._extractTextFromHTML(html)
        markdown = await self._extractDocumentsFromPage(html, page_url, markdown)
        return markdown

    async def _extractTextFromHTML(self, html_content: str) -> str:
        """Convert HTML to Markdown using trafilatura + cleanup"""
        try:
            import trafilatura
            from markdownify import markdownify as md

            extracted = trafilatura.extract(html_content, include_comments=False)
            markdown = md(extracted, heading_style="atx") if extracted else await self._cleanTextManually(html_content)

            markdown = await self._normalizeMarkdownText(markdown)
            logger.info(f"✅ [CONTENT] {len(markdown)} characters")
            return markdown
        except Exception as e:
            logger.error(f"❌ HTML to Markdown conversion failed: {e}")
            raise

    async def _cleanTextManually(self, html_content: str) -> str:
        """Fallback: manual HTML cleaning if trafilatura fails"""
        from markdownify import markdownify as md
        from bs4 import BeautifulSoup

        soup = BeautifulSoup(html_content, 'lxml')
        for element in soup(["script", "style", "nav", "footer", "header", "aside", "form", "button", "meta", "link", "noscript"]):
            element.extract()

        return md(str(soup), heading_style="atx")

    async def _normalizeMarkdownText(self, markdown: str) -> str:
        """Remove empty lines, noise, and excessive blank lines"""
        lines = [line.rstrip() for line in markdown.split('\n')]
        lines = [line for line in lines if line.strip()]
        lines = [line for line in lines if len(line) > 2 or line.startswith('#')]

        markdown = '\n'.join(lines)
        while '\n\n\n' in markdown:
            markdown = markdown.replace('\n\n\n', '\n\n')

        return markdown

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

            markdown_content, _ = await process_with_docling(temp_path, filename, mime_type, timeout_seconds=30)

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

        genai_client = get_genai_client()
        if not genai_client:
            raise Exception("Gemini client not configured")

        fd, temp_file = tempfile.mkstemp(suffix='.md')

        try:
            os.write(fd, page_data.markdown.encode('utf-8'))
            os.close(fd)

            metrics = calculate_metrics(page_data.markdown)
            doc_name = f"page_{job_context.website_id}_{int(time.time())}"

            logger.info(f"   📤 Uploading: {doc_name} ({metrics.get('file_size_bytes', 0):,} bytes)")

            operation = genai_client.file_search_stores.upload_to_file_search_store(
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
                os.close(fd)
            except:
                pass
            self._deleteTemporaryFile(temp_file)

    async def _buildGeminiUploadConfig(self, doc_name: str, website_id: int, page_url: str) -> Dict:
        """Build Gemini upload configuration"""
        return {
            'display_name': doc_name,
            'mime_type': 'text/markdown',
            'custom_metadata': [
                {'key': 'source_type', 'string_value': 'website'},
                {'key': 'website_id', 'string_value': str(website_id)},
                {'key': 'page_url', 'string_value': page_url}
            ]
        }

    def _deleteTemporaryFile(self, temp_file: str):
        """Clean up temporary file"""
        try:
            os.unlink(temp_file)
        except:
            pass

    async def _waitForGeminiUploadCompletion(self, operation, job_context: JobContext) -> Optional[UploadResult]:
        """Poll Gemini upload operation until done"""
        from core.ai import get_genai_client

        genai_client = get_genai_client()
        start_time = time.time()
        max_wait = 300

        while not operation.done:
            if await self._isTaskCancelled(job_context.celery_task_id):
                logger.error(f"   ❌ Task cancelled during upload polling")
                return None

            elapsed = time.time() - start_time
            if elapsed > max_wait:
                logger.error(f"   ❌ Timeout uploading ({elapsed:.0f}s)")
                return None

            logger.info(f"   ⏳ Waiting for upload... ({elapsed:.0f}s)")
            await asyncio.sleep(5)
            operation = genai_client.operations.get(operation)

        return await self._extractDocumentNameFromOperation(operation, job_context.store_name)

    async def _extractDocumentNameFromOperation(self, operation, store_name: str) -> Optional[UploadResult]:
        """Extract document name from completed upload operation"""
        if operation.done and hasattr(operation, 'response') and hasattr(operation.response, 'document_name'):
            doc_name = operation.response.document_name
            logger.info(f"   ✅ FileSearch document: {doc_name}")
            return UploadResult(
                document_name=doc_name,
                file_search_store_name=store_name,
                uploaded_at=datetime.utcnow()
            )

        logger.error(f"   ❌ Upload failed or invalid response")
        return None

    # ==================== DATABASE LAYER ====================

    async def _recordPageToDB(
        self,
        page_data: PageData,
        upload_result: UploadResult,
        job_context: JobContext
    ) -> Optional[int]:
        """Record single page in database"""
        if await self._isSinglePageMode(page_data.page_url, job_context.root_url):
            logger.info(f"   ℹ️ Skipping child record (single-page depth=0)")
            return job_context.website_id

        child_page_id = await self.scraping_dao.record_child_page(
            parent_id=job_context.website_id,
            page_url=page_data.page_url,
            gemini_file_name=upload_result.document_name,
            file_search_metadata=upload_result.file_search_metadata,
            user_role_id=job_context.user_role_id,
            file_size=calculate_metrics(page_data.markdown).get('file_size_bytes', 0),
            char_count=calculate_metrics(page_data.markdown).get('char_count', 0)
        )

        return child_page_id

    async def _isSinglePageMode(self, page_url: str, root_url: str) -> bool:
        """Check if child record should be skipped"""
        return page_url == root_url

    async def _recordWebsiteToDB(self, finalize_request: FinalizeRequest):
        """Update parent website record with aggregate stats via DAO"""
        metadata = {
            "type": "file_search",
            "file_search_store_name": finalize_request.file_search_store_name,
            "pages_count": finalize_request.page_count,
            "uploaded_at": datetime.utcnow().isoformat()
        }

        success = await self.scraping_dao.finalize_website_metadata(
            website_id=finalize_request.website_id,
            page_count=finalize_request.page_count,
            total_size_bytes=finalize_request.total_size_bytes,
            total_char_count=finalize_request.total_char_count,
            file_search_metadata=metadata
        )

        if not success:
            raise Exception(f"Failed to finalize website record {finalize_request.website_id}")

        logger.info(f"✅ Finalized: {finalize_request.page_count} pages, {finalize_request.total_size_bytes:,} bytes")

    # ==================== CANCELLATION ====================

    async def _isTaskCancelled(self, celery_task_id: str) -> bool:
        """Check if task marked for cancellation via Redis"""
        if not celery_task_id:
            return False

        try:
            import redis as redis_lib
            redis_url = os.getenv('WEB_REDIS_URL', 'redis://localhost:6379/1')

            try:
                redis_conn = redis_lib.from_url(redis_url, socket_connect_timeout=2)
                result = redis_conn.exists(f"task_cancelled:{celery_task_id}")
                redis_conn.close()
                return bool(result)
            except redis_lib.ConnectionError:
                logger.debug(f"ℹ️ Redis unavailable (OK in local dev)")
                return False
        except Exception as e:
            logger.debug(f"ℹ️ Skipping cancellation check: {e}")
            return False

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
