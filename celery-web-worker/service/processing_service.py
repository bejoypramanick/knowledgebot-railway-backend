"""
Website Processing Service for Celery Web Worker
Handles all website scraping, content extraction, and Gemini FileSearch upload
"""
import asyncio
import time
from datetime import datetime
from typing import Dict, List, Any, Optional
import logging

from shared.otel_logger import get_otel_logger
from shared.file_search import get_file_search_store_by_display_name

logger = get_otel_logger("processing_service", "celery-web-worker")


class ProcessingService:
    """Handle website scraping and content processing"""

    def __init__(self):
        from ..dao.scraping_dao import ScrapingDAO
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
                user_email=user_email
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

            return {
                "success": True,
                "message": f"Website processed successfully: {len(processed_pages)} pages",
                "website_id": website_id,
                "page_count": len(processed_pages),
                "processing_time_seconds": processing_time,
                "gemini_file_name": file_search_result.get("gemini_file_name"),
                "file_search_metadata": file_search_result.get("file_search_metadata")
            }

        except Exception as e:
            logger.error(f"❌ Unexpected error processing website {website_id}: {e}", exc_info=True)
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
            import os

            redis_url = os.getenv('REDIS_URL', 'redis://localhost:6379/1')
            redis_conn = redis_lib.from_url(redis_url)

            cancelled_key = f"task_cancelled:{celery_task_id}"
            result = redis_conn.exists(cancelled_key)
            redis_conn.close()

            return bool(result)
        except Exception as e:
            logger.warning(f"⚠️ Error checking cancellation status: {e}")
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
            from crawl4ai import AsyncWebCrawler, CrawlResult

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
                                logger.warning(f"⚠️ Failed to fetch {page_url}")
                                return None

                    except Exception as e:
                        logger.error(f"❌ Error fetching {page_url}: {e}")
                        return None

            # BFS crawling with depth control
            while to_visit and len(pages) < max_pages:
                current_url, current_depth = to_visit.pop(0)

                # Skip if already visited or depth exceeded
                if current_url in visited_urls or current_depth > max_depth:
                    continue

                visited_urls.add(current_url)

                # Fetch page
                result = await fetch_page(current_url)
                if result:
                    pages.append(result)
                    page_url, page_html = result

                    # Extract links for next level if depth allows
                    if current_depth < max_depth and len(pages) < max_pages:
                        try:
                            from bs4 import BeautifulSoup

                            soup = BeautifulSoup(page_html, 'lxml')
                            base_domain = self._get_domain(url)

                            for link in soup.find_all('a', href=True):
                                href = link['href']
                                # Convert relative URLs to absolute
                                if href.startswith('/'):
                                    href = f"{base_domain}{href}"
                                elif not href.startswith('http'):
                                    continue

                                # Only crawl same domain
                                if self._get_domain(href) == base_domain and href not in visited_urls:
                                    to_visit.append((href, current_depth + 1))
                                    if len(pages) >= max_pages:
                                        break

                        except Exception as e:
                            logger.warning(f"⚠️ Failed to extract links from {current_url}: {e}")

            logger.info(f"✅ Crawling complete: {len(pages)} pages collected")
            return pages

        except Exception as e:
            logger.error(f"❌ Website scraping failed: {e}", exc_info=True)
            return []

    async def _html_to_markdown(self, html_content: str) -> str:
        """Convert HTML content to Markdown"""
        try:
            from markdownify import markdownify as md
            from bs4 import BeautifulSoup

            # Clean HTML: remove script, style, nav, footer, header elements
            soup = BeautifulSoup(html_content, 'lxml')
            for element in soup(["script", "style", "nav", "footer", "header", "aside"]):
                element.extract()

            # Convert to markdown
            markdown = md(str(soup), heading_style="atx")

            # Clean up excessive whitespace
            lines = markdown.split('\n')
            lines = [line.rstrip() for line in lines]
            lines = [line for line in lines if line.strip()]  # Remove empty lines
            markdown = '\n'.join(lines)

            return markdown

        except Exception as e:
            logger.error(f"❌ HTML to Markdown conversion failed: {e}")
            raise

    async def _upload_to_gemini(
        self,
        website_id: int,
        url: str,
        processed_pages: List[Dict[str, str]],
        user_email: str
    ) -> Dict[str, Any]:
        """Upload website content to Gemini FileSearch"""
        try:
            from knowledgebase_ingestion.core.ai import get_genai_client
            from knowledgebase_ingestion.core.config import settings
            import json

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

            logger.info(f"📤 Uploading to FileSearch store: {file_search_store_name}")

            # Combine all pages into single document
            combined_markdown = "\n\n---\n\n".join([
                f"## {page['url']}\n\n{page['markdown']}"
                for page in processed_pages
            ])

            # Create temp file with markdown content
            import tempfile
            import os

            with tempfile.NamedTemporaryFile(mode='w', suffix='.md', delete=False) as f:
                f.write(combined_markdown)
                temp_file = f.name

            try:
                # Upload to Gemini
                with open(temp_file, 'rb') as f:
                    file_response = genai_client.files.upload(file=f)
                    gemini_file_name = file_response.name

                logger.info(f"✅ Uploaded to Gemini: {gemini_file_name}")

                # Upload to FileSearch
                document_name = f"website_{website_id}_{int(time.time())}"
                file_search_response = genai_client.file_search_stores.documents.create(
                    parent=file_search_store_name,
                    display_name=document_name,
                    mime_type="text/markdown"
                )

                logger.info(f"✅ Created FileSearch document: {file_search_response.name}")

                return {
                    "success": True,
                    "gemini_file_name": gemini_file_name,
                    "file_search_metadata": {
                        "type": "file_search",
                        "file_search_store_name": file_search_store_name,
                        "document_name": file_search_response.name,
                        "gemini_file_name": gemini_file_name,
                        "uploaded_at": datetime.utcnow().isoformat()
                    }
                }

            finally:
                # Clean up temp file
                try:
                    os.unlink(temp_file)
                except:
                    pass

        except Exception as e:
            logger.error(f"❌ Gemini upload failed: {e}", exc_info=True)
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
        """Record website metadata in database"""
        try:
            from shared.db import get_db_connection
            import json

            async with get_db_connection() as conn:
                await conn.execute(
                    """UPDATE scraped_websites
                       SET gemini_file_name = $1,
                           metadata = $2,
                           processing_status = 'completed',
                           updated_at = NOW()
                       WHERE id = $3""",
                    gemini_file_name,
                    json.dumps(file_search_metadata),
                    website_id
                )

            logger.info(f"✅ Recorded metadata for website {website_id}")

            return {
                "success": True,
                "website_id": website_id,
                "page_count": page_count
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
