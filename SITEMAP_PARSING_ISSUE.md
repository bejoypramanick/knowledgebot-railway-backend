# Sitemap Parsing Issue

## Problem

Sitemap URLs (e.g., `https://www.scania.com/group/en/sitemap.xml`) are failing with error: **"No pages successfully processed"**

## Root Cause

The current scraping system treats sitemaps as regular HTML pages, but sitemaps are XML files with a specific structure that needs special parsing.

### Current Flow (Broken for Sitemaps):
```
1. User submits sitemap URL
2. System fetches sitemap.xml as HTML
3. Tries to extract links using BeautifulSoup HTML parser
4. Fails to find any valid links (XML structure != HTML structure)
5. No pages processed → Error: "No pages successfully processed"
```

## Sitemap XML Structure

Sitemaps use XML format, not HTML:

```xml
<?xml version="1.0" encoding="UTF-8"?>
<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">
  <url>
    <loc>https://www.example.com/page1</loc>
    <lastmod>2024-01-01</lastmod>
    <priority>0.8</priority>
  </url>
  <url>
    <loc>https://www.example.com/page2</loc>
    <lastmod>2024-01-02</lastmod>
    <priority>0.6</priority>
  </url>
</urlset>
```

## Solution Needed

Add sitemap-specific parsing logic to extract URLs from XML:

### 1. Detect Sitemap URLs
Already implemented in `webcrawl_dao.py` and `scraping_dao.py`:
```python
is_sitemap = (
    url.endswith('sitemap.xml') or
    url.endswith('sitemap.xml.gz') or
    url.endswith('sitemap_index.xml') or
    '/sitemap' in url and url.endswith('.xml')
)
```

### 2. Add XML Parsing Logic
Need to add in `processing_service.py`:

```python
async def _parseSitemapXML(self, xml_content: str) -> List[str]:
    """Parse sitemap XML and extract URLs"""
    import xml.etree.ElementTree as ET
    
    urls = []
    try:
        root = ET.fromstring(xml_content)
        
        # Handle namespace
        ns = {'ns': 'http://www.sitemaps.org/schemas/sitemap/0.9'}
        
        # Extract <loc> elements
        for url_elem in root.findall('.//ns:url/ns:loc', ns):
            if url_elem.text:
                urls.append(url_elem.text.strip())
        
        # Handle sitemap index (contains other sitemaps)
        for sitemap_elem in root.findall('.//ns:sitemap/ns:loc', ns):
            if sitemap_elem.text:
                # Recursively fetch nested sitemaps
                urls.append(sitemap_elem.text.strip())
        
        logger.info(f"📋 Extracted {len(urls)} URLs from sitemap")
        return urls
        
    except ET.ParseError as e:
        logger.error(f"❌ Failed to parse sitemap XML: {e}")
        return []
```

### 3. Modify BFS Crawl Logic
Update `_crawlPagesWithBFS` to handle sitemaps:

```python
# After fetching page HTML
if is_sitemap_url(current_url):
    # Parse as sitemap XML
    sitemap_urls = await self._parseSitemapXML(page_html)
    
    # Add all sitemap URLs to crawl queue
    for url in sitemap_urls:
        if url not in visited_urls:
            to_visit.append((url, current_depth + 1))
    
    # Don't process sitemap itself as a page
    continue
else:
    # Normal HTML page processing
    yield PageData(...)
```

## Implementation Steps

1. ✅ Detect sitemap URLs (already done)
2. ⏳ Add `_parseSitemapXML()` method
3. ⏳ Modify `_crawlPagesWithBFS()` to use XML parser for sitemaps
4. ⏳ Handle sitemap index files (sitemaps that reference other sitemaps)
5. ⏳ Handle compressed sitemaps (`.xml.gz`)
6. ⏳ Test with real sitemap URLs

## Testing URLs

- Standard: `https://www.scania.com/group/en/sitemap.xml`
- Index: `https://www.example.com/sitemap_index.xml`
- Compressed: `https://www.example.com/sitemap.xml.gz`

## Notes

- Sitemaps can contain up to 50,000 URLs
- Sitemap index files can reference multiple sitemaps
- Need to respect `max_pages` limit when processing sitemap URLs
- Consider adding priority/lastmod filtering options
