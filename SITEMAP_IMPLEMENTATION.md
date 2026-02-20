# Sitemap Implementation Using Crawl4ai

## Good News!

Crawl4ai has built-in sitemap support through the `AsyncUrlSeeder` class. We don't need to write custom XML parsing!

## How Crawl4ai Handles Sitemaps

```python
from crawl4ai import AsyncUrlSeeder, SeedingConfig

# Discover URLs from sitemap
async with AsyncUrlSeeder() as seeder:
    config = SeedingConfig(
        source="sitemap",           # Use sitemap as source
        extract_head=True,          # Get page metadata
        max_urls=100,               # Limit URLs
        pattern="*",                # URL pattern filter
        live_check=False            # Don't verify URLs (faster)
    )
    
    urls = await seeder.urls("example.com", config)
    
    # urls is a list of dicts:
    # [
    #   {
    #     "url": "https://example.com/page1",
    #     "status": "valid",
    #     "head_data": {...}
    #   },
    #   ...
    # ]
```

## Features We Get For Free

1. **Automatic Sitemap Detection**: Finds sitemap.xml automatically
2. **Sitemap Index Support**: Handles sitemap indexes (sitemaps of sitemaps)
3. **Parallel Processing**: Processes multiple sitemaps in parallel
4. **Compressed Sitemaps**: Handles .xml.gz files
5. **URL Filtering**: Built-in pattern matching
6. **Metadata Extraction**: Can extract page titles, descriptions, etc.

## Implementation Plan

### Step 1: Detect Sitemap URLs
Already done in `webcrawl_dao.py` and `scraping_dao.py`

### Step 2: Add Sitemap URL Discovery Method
Add to `processing_service.py`:

```python
async def _discoverSitemapURLs(
    self,
    sitemap_url: str,
    max_urls: int = 100
) -> List[str]:
    """
    Discover URLs from a sitemap using crawl4ai's AsyncUrlSeeder.
    
    Args:
        sitemap_url: URL of the sitemap
        max_urls: Maximum URLs to extract
        
    Returns:
        List of URLs found in the sitemap
    """
    try:
        from crawl4ai import AsyncUrlSeeder, SeedingConfig
        from urllib.parse import urlparse
        
        # Extract domain from sitemap URL
        parsed = urlparse(sitemap_url)
        domain = parsed.netloc
        
        logger.info(f"🗺️ [SITEMAP] Discovering URLs from {sitemap_url}")
        
        async with AsyncUrlSeeder() as seeder:
            config = SeedingConfig(
                source="sitemap",
                max_urls=max_urls,
                extract_head=False,  # Don't need metadata, just URLs
                live_check=False,    # Don't verify (faster)
                filter_nonsense_urls=True  # Filter out utility URLs
            )
            
            # Discover URLs
            url_results = await seeder.urls(domain, config)
            
            # Extract just the URL strings
            urls = [result["url"] for result in url_results if result.get("status") != "not_valid"]
            
            logger.info(f"✅ [SITEMAP] Discovered {len(urls)} URLs from sitemap")
            return urls
            
    except Exception as e:
        logger.error(f"❌ [SITEMAP] Failed to discover URLs: {e}")
        return []
```

### Step 3: Modify BFS Crawl Logic
Update `_crawlPagesWithBFS` to handle sitemaps:

```python
async def _crawlPagesWithBFS(
    self,
    crawl_config: CrawlConfig,
    job_context: JobContext
) -> AsyncGenerator[PageData, None]:
    """Async generator yielding PageData one at a time"""
    
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
        
        # Add all sitemap URLs to crawl queue
        to_visit = [(url, 1) for url in sitemap_urls]  # depth=1 for all sitemap URLs
        visited_urls = set()
    else:
        # Normal BFS crawl
        visited_urls = set()
        to_visit = [(job_context.root_url, 0)]
    
    # Rest of BFS logic remains the same...
    semaphore = asyncio.Semaphore(crawl_config.max_concurrent)
    pages_yielded = 0
    
    while to_visit and pages_yielded < crawl_config.max_pages:
        current_url, current_depth = to_visit.pop(0)
        
        # ... existing crawl logic ...
```

### Step 4: Add Helper Method
```python
def _isSitemapURL(self, url: str) -> bool:
    """Check if URL is a sitemap"""
    url_lower = url.lower()
    return (
        url_lower.endswith('sitemap.xml') or
        url_lower.endswith('sitemap.xml.gz') or
        url_lower.endswith('sitemap_index.xml') or
        '/sitemap' in url_lower and url_lower.endswith('.xml')
    )
```

## Benefits

✅ **No custom XML parsing needed**
✅ **Handles sitemap indexes automatically**
✅ **Supports compressed sitemaps**
✅ **Built-in URL filtering**
✅ **Parallel processing**
✅ **Memory efficient**

## Testing

Test with these URLs:
- `https://www.scania.com/group/en/sitemap.xml`
- `https://techcrunch.com/sitemap.xml`
- `https://www.python.org/sitemap.xml`

## Next Steps

1. Implement `_discoverSitemapURLs()` method
2. Update `_crawlPagesWithBFS()` to detect and handle sitemaps
3. Add `_isSitemapURL()` helper method
4. Test with real sitemap URLs
5. Update error handling for sitemap-specific errors
