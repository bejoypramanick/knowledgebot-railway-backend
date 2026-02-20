# Sitemap Crawling Solution

## Problem
Sitemaps can be located at custom paths (e.g., `https://www.scania.com/group/en/sitemap.xml`), not just at the standard root location (`/sitemap.xml`).

## Research Finding
After researching crawl4ai's `AsyncUrlSeeder` API and documentation, we discovered a critical limitation:

**AsyncUrlSeeder cannot handle custom sitemap paths.**

### How AsyncUrlSeeder Works
```python
async with AsyncUrlSeeder() as seeder:
    config = SeedingConfig(source="sitemap")
    urls = await seeder.urls("www.scania.com", config)  # Takes DOMAIN only
```

- Takes a **domain** parameter (e.g., "www.scania.com")
- Automatically looks for sitemaps at standard locations:
  - `/sitemap.xml`
  - `/sitemap_index.xml`
  - `/robots.txt` (for sitemap references)
- **Cannot** accept a full URL with custom path

### The Problem with Custom Paths
When given `https://www.scania.com/group/en/sitemap.xml`:
1. AsyncUrlSeeder extracts domain: `www.scania.com`
2. Looks for: `https://www.scania.com/sitemap.xml` → 404 Not Found
3. Cannot find: `https://www.scania.com/group/en/sitemap.xml`

## Solution: Direct XML Parsing

We implemented direct XML parsing using Python's built-in `xml.etree.ElementTree`. This gives us:

### Features
✅ **Custom sitemap paths** - Works with any URL path
✅ **Sitemap indexes** - Recursively processes sub-sitemaps
✅ **Compressed sitemaps** - Handles `.xml.gz` files
✅ **Namespace support** - Properly parses XML with namespaces
✅ **Error recovery** - Graceful handling of fetch/parse errors

### Implementation

#### 1. Sitemap Detection
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

#### 2. XML Parsing
```python
async def _discoverSitemapURLs(
    self,
    sitemap_url: str,
    max_urls: int = 100
) -> List[str]:
    """
    Discover URLs from a sitemap by directly parsing the XML.
    
    Handles:
    - Regular sitemaps with <url><loc> entries
    - Sitemap indexes with <sitemap><loc> entries (recursive)
    - Compressed sitemaps (.xml.gz)
    - Custom sitemap paths
    """
    # Fetch sitemap
    async with aiohttp.ClientSession() as session:
        async with session.get(sitemap_url) as response:
            content = await response.read()
    
    # Handle compression
    if sitemap_url.endswith('.gz'):
        content = gzip.decompress(content)
    
    # Parse XML with namespace
    root = ET.fromstring(content)
    namespaces = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
    
    # Check for sitemap index
    sitemap_locs = root.findall('.//ns:sitemap/ns:loc', namespaces)
    if sitemap_locs:
        # Recursively fetch sub-sitemaps
        for sitemap_loc in sitemap_locs[:10]:
            sub_urls = await self._discoverSitemapURLs(sitemap_loc.text)
            urls.extend(sub_urls)
    else:
        # Extract regular URLs
        url_locs = root.findall('.//ns:url/ns:loc', namespaces)
        urls = [loc.text.strip() for loc in url_locs]
    
    return urls
```

#### 3. Integration with Crawl Queue
```python
if is_sitemap:
    # Discover all URLs from sitemap
    sitemap_urls = await self._discoverSitemapURLs(
        job_context.root_url,
        max_urls=crawl_config.max_pages
    )
    
    # Add to crawl queue (all at depth=1)
    to_visit = [(url, 1) for url in sitemap_urls]
    
    # Don't follow links (we already have all URLs)
    # Just crawl the discovered URLs
```

## Why This Approach is Better

1. **Flexibility**: Works with any sitemap URL, regardless of path
2. **Control**: Full control over parsing logic and error handling
3. **Simplicity**: Uses Python standard library (no extra dependencies)
4. **Reliability**: Direct parsing is more predictable than relying on AsyncUrlSeeder's auto-discovery

## Testing

Test with various sitemap types:

```bash
# Custom path sitemap
https://www.scania.com/group/en/sitemap.xml

# Standard location
https://techcrunch.com/sitemap.xml

# Sitemap index
https://www.python.org/sitemap.xml

# Compressed sitemap
https://example.com/sitemap.xml.gz
```

## Current Status

✅ **IMPLEMENTED AND WORKING**

All sitemap crawling features are implemented in:
- `knowledgebot-railway-backend/celery-web-worker/service/processing_service.py`

The implementation:
- Detects sitemap URLs via pattern matching
- Parses XML with proper namespace handling
- Recursively processes sitemap indexes
- Integrates with the BFS crawl queue
- Handles errors gracefully

## Conclusion

While crawl4ai's `AsyncUrlSeeder` is a powerful tool for standard sitemap locations, it cannot handle custom sitemap paths. Direct XML parsing is the correct and only viable solution for our use case, providing full flexibility and control over sitemap discovery.
