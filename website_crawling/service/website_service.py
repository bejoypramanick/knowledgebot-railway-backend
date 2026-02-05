"""
Website Service Layer for Website Crawling
Provides business logic for website scraping and crawling operations with session management
"""
import asyncio
import time
import re
import uuid
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse, urljoin
from datetime import datetime

from website_crawling.core.otel_logger import get_otel_logger
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
        timeout = options.get("timeout", 30)

        logger.info(f"🌐 Starting scrape for {url} - max_pages={max_pages}, max_depth={max_depth}")

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
                # Limit to max_pages
                urls_to_scrape = sitemap_urls[:max_pages]

                # Scrape all URLs from sitemap
                result = await self._scrape_urls_from_sitemap(urls_to_scrape, timeout)

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
                    result = await self._scrape_with_crawl4ai(url, max_pages, max_depth, timeout)
                elif HTTPX_AVAILABLE:
                    result = await self._scrape_with_httpx(url, max_pages, max_depth, timeout)
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
                logger.warning(f"⚠️ Docling processing error for {url}: {e} - falling back to raw")

        # Upload to Gemini
        from website_crawling.service.ai_service import upload_content_to_gemini, record_scraped_metadata

        # Get domain
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
                "max_depth": max_depth
            }
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
        timeout: int
    ) -> Dict[str, Any]:
        """Scrape using crawl4ai library."""
        all_content = []
        scraped_urls: Set[str] = set()
        urls_to_scrape = [(url, 0)]  # (url, depth)
        title = "Untitled"

        try:
            async with AsyncWebCrawler(verbose=False) as crawler:
                while urls_to_scrape and len(scraped_urls) < max_pages:
                    current_url, depth = urls_to_scrape.pop(0)

                    if current_url in scraped_urls:
                        continue

                    logger.info(f"📄 Scraping page {len(scraped_urls) + 1}/{max_pages}: {current_url} (depth={depth})")

                    try:
                        result = await asyncio.wait_for(
                            crawler.arun(url=current_url),
                            timeout=timeout
                        )

                        if result.success:
                            scraped_urls.add(current_url)

                            # Get content
                            content = result.markdown or result.cleaned_html or result.html or ""
                            if content:
                                all_content.append(f"\n\n--- Page: {current_url} ---\n\n{content}")

                            # Get title from first page
                            if len(scraped_urls) == 1 and hasattr(result, 'title') and result.title:
                                title = result.title

                            # Extract links for further crawling
                            if depth < max_depth and len(scraped_urls) < max_pages:
                                links = extract_links_from_result(result, current_url)
                                for link in links:
                                    if link not in scraped_urls and (link, depth + 1) not in urls_to_scrape:
                                        urls_to_scrape.append((link, depth + 1))

                        else:
                            logger.warning(f"⚠️ Failed to scrape {current_url}: {result.error_message}")

                    except asyncio.TimeoutError:
                        logger.warning(f"⏱️ Timeout scraping {current_url}")
                    except Exception as e:
                        logger.warning(f"⚠️ Error scraping {current_url}: {e}")

            combined_content = "\n".join(all_content)

            return {
                "success": len(scraped_urls) > 0,
                "content": combined_content,
                "title": title,
                "pages_scraped": len(scraped_urls),
                "scraped_urls": list(scraped_urls)
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
        timeout: int
    ) -> Dict[str, Any]:
        """Fallback scraping using httpx and BeautifulSoup."""
        all_content = []
        scraped_urls: Set[str] = set()
        urls_to_scrape = [(url, 0)]  # (url, depth)
        title = "Untitled"

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
                    response = await client.get(current_url, headers=headers)
                    response.raise_for_status()

                    scraped_urls.add(current_url)

                    # Parse HTML
                    soup = BeautifulSoup(response.text, 'lxml')

                    # Remove script and style elements
                    for element in soup(['script', 'style', 'nav', 'footer', 'header']):
                        element.decompose()

                    # Get title from first page
                    if len(scraped_urls) == 1:
                        title_tag = soup.find('title')
                        if title_tag:
                            title = title_tag.get_text(strip=True)

                    # Extract text content
                    text = soup.get_text(separator='\n', strip=True)
                    # Clean up excessive whitespace
                    text = re.sub(r'\n{3,}', '\n\n', text)

                    if text:
                        all_content.append(f"\n\n--- Page: {current_url} ---\n\n{text}")

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
                                if clean_url not in scraped_urls:
                                    urls_to_scrape.append((clean_url, depth + 1))

                except httpx.HTTPStatusError as e:
                    logger.warning(f"⚠️ HTTP error scraping {current_url}: {e.response.status_code}")
                except Exception as e:
                    logger.warning(f"⚠️ Error scraping {current_url}: {e}")

        combined_content = "\n".join(all_content)

        return {
            "success": len(scraped_urls) > 0,
            "content": combined_content,
            "title": title,
            "pages_scraped": len(scraped_urls),
            "scraped_urls": list(scraped_urls)
        }

    async def _scrape_urls_from_sitemap(
        self,
        urls: List[str],
        timeout: int
    ) -> Dict[str, Any]:
        """Scrape multiple URLs from a sitemap."""
        all_content = []
        scraped_urls: Set[str] = set()
        title = "Sitemap Collection"

        headers = {
            "User-Agent": "KnowledgeBot-Crawler/1.0 (+https://globistaan.com)"
        }

        try:
            import httpx
            from bs4 import BeautifulSoup

            async with httpx.AsyncClient(timeout=timeout, follow_redirects=True) as client:
                for i, url in enumerate(urls):
                    logger.info(f"📄 Scraping URL {i+1}/{len(urls)}: {url}")

                    try:
                        response = await client.get(url, headers=headers)
                        response.raise_for_status()

                        scraped_urls.add(url)

                        # Parse HTML
                        soup = BeautifulSoup(response.text, 'lxml')

                        # Remove script and style elements
                        for element in soup(['script', 'style', 'nav', 'footer', 'header']):
                            element.decompose()

                        # Get title from first page if not set
                        if i == 0:
                            title_tag = soup.find('title')
                            if title_tag:
                                title = title_tag.get_text(strip=True)

                        # Extract text content
                        text = soup.get_text(separator='\n', strip=True)
                        text = re.sub(r'\n{3,}', '\n\n', text)

                        if text:
                            all_content.append(f"\n\n--- Page: {url} ---\n\n{text}")

                    except httpx.HTTPStatusError as e:
                        logger.warning(f"⚠️ HTTP error scraping {url}: {e.response.status_code}")
                    except Exception as e:
                        logger.warning(f"⚠️ Error scraping {url}: {e}")

            combined_content = "\n".join(all_content)

            return {
                "success": len(scraped_urls) > 0,
                "content": combined_content,
                "title": title,
                "pages_scraped": len(scraped_urls),
                "scraped_urls": list(scraped_urls)
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
            from website_crawling.core.db import get_db_connection
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
            from website_crawling.core.db import get_db_connection
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

    async def delete_job(self, job_id: str) -> Dict[str, Any]:
        """Delete a scraping job."""
        try:
            from website_crawling.core.db import get_db_connection
            from website_crawling.core.ai import get_genai_client

            # First get the record to find Gemini file
            job = await self.get_job_details(job_id)
            if not job:
                return {"success": False, "error": "Job not found"}

            # Delete from Gemini if file exists
            gemini_file_name = job.get("gemini_file_name")
            if gemini_file_name:
                genai_client = get_genai_client()
                if genai_client:
                    try:
                        genai_client.files.delete(name=gemini_file_name)
                        logger.info(f"🗑️ Deleted Gemini file: {gemini_file_name}")
                    except Exception as e:
                        logger.warning(f"⚠️ Could not delete Gemini file: {e}")

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
            from website_crawling.core.db import get_db_connection
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
            from website_crawling.core.db import get_db_connection
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
            from website_crawling.core.db import get_db_connection
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
