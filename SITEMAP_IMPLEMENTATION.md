# Sitemap Implementation

## Implementation Approach

We use **direct XML parsing** to handle sitemaps because:
- Sitemaps can be at custom paths (e.g., `/group/en/sitemap.xml`)
- Crawl4ai's `AsyncUrlSeeder` only works with standard sitemap locations at domain root
- Direct parsing gives us full control over sitemap discovery and URL extraction

## How We Handle Sitemaps

We directly parse sitemap XML files using Python's built-in `xml.etree.ElementTree`:

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
    - Custom sitemap paths (e.g., /group/en/sitemap.xml)
    """
```

## Why Not AsyncUrlSeeder?

Crawl4ai's `AsyncUrlSeeder` has a limitation:
- It takes a **domain** parameter (e.g., "www.scania.com")
- It only looks for sitemaps at standard locations: `/sitemap.xml`, `/sitemap_index.xml`
- It **cannot** handle custom sitemap paths like `/group/en/sitemap.xml`

Example of the limitation:
```python
# This doesn't work for custom paths:
async with AsyncUrlSeeder() as seeder:
    config = SeedingConfig(source="sitemap")
    # Looks for www.scania.com/sitemap.xml (404)
    # Cannot find www.scania.com/group/en/sitemap.xml
    urls = await seeder.urls("www.scania.com", config)
```

## Features We Get

1. **Custom Sitemap Paths**: Handles sitemaps at any URL path
2. **Sitemap Index Support**: Recursively processes sitemap indexes
3. **Compressed Sitemaps**: Handles .xml.gz files
4. **Namespace Handling**: Properly parses XML with namespaces
5. **Error Recovery**: Graceful handling of fetch/parse errors

## Implementation Details

## Implementation Details

### Step 1: Sitemap Detection
Already implemented in `_isSitemapURL()`:

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

### Step 2: XML Parsing with Namespace Support
The implementation handles the standard sitemap namespace:

```python
namespaces = {
    'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9',
    'xhtml': 'http://www.w3.org/1999/xhtml'
}

# Check for sitemap index
sitemap_locs = root.findall('.//ns:sitemap/ns:loc', namespaces)

# Extract regular URLs
url_locs = root.findall('.//ns:url/ns:loc', namespaces)
```

### Step 3: Recursive Sitemap Index Handling
When a sitemap index is detected, it recursively fetches sub-sitemaps:

```python
if sitemap_locs:
    logger.info(f"📋 [SITEMAP] Found sitemap index with {len(sitemap_locs)} sub-sitemaps")
    
    for sitemap_loc in sitemap_locs[:10]:  # Limit to 10 sub-sitemaps
        sub_sitemap_url = sitemap_loc.text.strip()
        sub_urls = await self._discoverSitemapURLs(
            sub_sitemap_url,
            max_urls=max_urls - len(urls)
        )
        urls.extend(sub_urls)
```

### Step 4: Integration with BFS Crawl
The sitemap URLs are integrated into the crawl queue:

```python
if is_sitemap:
    logger.info(f"🗺️ [SITEMAP] Detected sitemap URL, using URL discovery")
    
    sitemap_urls = await self._discoverSitemapURLs(
        job_context.root_url,
        max_urls=crawl_config.max_pages
    )
    
    # Add all sitemap URLs to crawl queue (depth=1 for all)
    to_visit = [(url, 1) for url in sitemap_urls]
    visited_urls = set()
```

## Benefits

✅ **Handles custom sitemap paths** (e.g., `/group/en/sitemap.xml`)
✅ **Recursive sitemap index support**
✅ **Compressed sitemap support** (.xml.gz)
✅ **Proper XML namespace handling**
✅ **Memory efficient** (limits URLs and sub-sitemaps)
✅ **Robust error handling**

## Current Status

✅ **IMPLEMENTED** - All features are working:
- Sitemap detection via URL pattern matching
- Direct XML parsing with namespace support
- Recursive sitemap index handling
- Integration with BFS crawl queue
- Proper error handling and logging

## Testing

Test with these URLs:
- `https://www.scania.com/group/en/sitemap.xml` - Custom path sitemap
- `https://techcrunch.com/sitemap.xml` - Standard location
- `https://www.python.org/sitemap.xml` - Standard location

## Known Limitations

1. **AsyncUrlSeeder not used**: Cannot handle custom sitemap paths
2. **Sub-sitemap limit**: Maximum 10 sub-sitemaps to prevent excessive recursion
3. **URL limit**: Respects `max_urls` parameter to control memory usage
