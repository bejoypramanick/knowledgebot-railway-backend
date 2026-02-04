"""
Scraping Service Layer for Website Crawling
Provides business logic for website scraping operations using crawl4ai
"""
import asyncio
import time
import re
from typing import Any, Dict, List, Optional, Set
from urllib.parse import urlparse, urljoin
from datetime import datetime

from website_crawling.core.otel_logger import get_otel_logger
from website_crawling.dao.scraping_dao import ScrapingDAO
from website_crawling.utils.links import extract_links_from_result

logger = get_otel_logger("scraping_service", "website-crawling")

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


class ScrapingService:
    """Service layer for website scraping operations"""

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

        # Perform the actual scraping
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

            if not result["success"]:
                return result

            # Upload to Gemini
            from website_crawling.service.ingestion_service import upload_content_to_gemini, record_scraped_metadata

            gemini_result = await upload_content_to_gemini(
                content=result["content"],
                url=url,
                title=result.get("title", "Untitled"),
                user_email=options.get("user_email")
            )

            # Record metadata to database
            domain = urlparse(url).netloc.replace('www.', '')
            record_id = await record_scraped_metadata(
                url=url,
                domain=domain,
                title=result.get("title", "Untitled"),
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

        except Exception as e:
            logger.error(f"❌ Error scraping website {url}: {e}")
            return {
                "success": False,
                "error": str(e),
                "url": url
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


# Singleton instance
scraping_service = ScrapingService()
