"""
Website Crawler Service
Handles website crawling operations
"""

from website_crawling.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)
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
