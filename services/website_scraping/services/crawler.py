import logging
import asyncio
from typing import List, Tuple
from crawl4ai import AsyncWebCrawler
from crawl4ai.async_configs import BrowserConfig, CrawlerRunConfig
from ..schemas.models import ScrapeRequest
from ..utils.links import extract_links_from_result
from fastapi import HTTPException

logger = logging.getLogger(__name__)

async def crawl_website(request: ScrapeRequest, sse_queue: asyncio.Queue = None) -> Tuple[str, List[str]]:
    """Crawl website and return aggregated content and list of URLs."""
    
    # Configure browser
    browser_config = BrowserConfig(verbose=False, headless=True)

    # Configure crawl options
    run_config = CrawlerRunConfig(
        max_pages_per_run=request.max_pages or 10,
        max_depth=request.max_depth or 2,
        wait_for=request.wait_for,
        js_code=request.js_code,
        screenshot=request.screenshot,
        exclude_external_links=True,
        scan_full_page=False,
    )

    scraped_content = ""
    scraped_urls = []

    async with AsyncWebCrawler(config=browser_config) as crawler:
        if sse_queue:
            await sse_queue.put({
                "type": "scraping_started",
                "message": f"Starting multi-page crawl of {request.url}",
                "url": request.url,
                "max_pages": request.max_pages,
                "max_depth": request.max_depth,
                "timestamp": asyncio.get_event_loop().time()
            })

        all_results = []
        crawled_urls = []
        pages_crawled = 0
        urls_to_process = [request.url]

        while urls_to_process and pages_crawled < (request.max_pages or 10):
            current_url = urls_to_process.pop(0)

            try:
                if sse_queue:
                    await sse_queue.put({
                        "type": "page_crawling",
                        "message": f"Crawling page {pages_crawled + 1}/{request.max_pages or 10}: {current_url}",
                        "url": current_url,
                        "page_number": pages_crawled + 1,
                        "timestamp": asyncio.get_event_loop().time()
                    })

                result = await crawler.arun(url=current_url, config=run_config)
                pages_crawled += 1

                if result.success:
                    all_results.append((current_url, result))
                    crawled_urls.append(current_url)
                    
                    if pages_crawled < (request.max_pages or 10):
                        new_links = extract_links_from_result(result, request.url)
                        for link in new_links:
                            if link not in crawled_urls and link not in urls_to_process:
                                urls_to_process.append(link)
                                if len(urls_to_process) >= (request.max_pages or 10) - pages_crawled:
                                    break
                else:
                    logger.warning(f"Failed to crawl {current_url}: {getattr(result, 'error_message', 'Unknown error')}")

            except Exception as e:
                logger.error(f"Error crawling {current_url}: {e}")

        if not all_results:
             # Just return empty, caller expects exception or empty
             raise HTTPException(500, "Failed to crawl any pages")

        for page_url, page_result in all_results:
            page_content = ""
            if hasattr(page_result, 'markdown'):
                if hasattr(page_result.markdown, 'raw_markdown'):
                    page_content = page_result.markdown.raw_markdown
                elif hasattr(page_result.markdown, 'fit_markdown'):
                    page_content = page_result.markdown.fit_markdown
                else:
                    page_content = str(page_result.markdown)
            
            if not page_content and hasattr(page_result, 'html'):
                page_content = page_result.html
            if not page_content and hasattr(page_result, 'cleaned_html'):
                page_content = page_result.cleaned_html

            if page_content:
                scraped_content += f"\n\n## Page: {page_url}\n\n{page_content}"
                scraped_urls.append(page_url)
                
                if sse_queue:
                    await sse_queue.put({
                        "type": "page_completed",
                        "message": f"Extracted content from {page_url} ({len(page_content)} chars)",
                        "url": page_url,
                        "content_length": len(page_content),
                        "timestamp": asyncio.get_event_loop().time()
                    })

    if not scraped_content:
        raise HTTPException(500, "No content extracted from any crawled pages")
        
    logger.info(f"Successfully crawled {len(scraped_urls)} pages")
    return scraped_content, scraped_urls
