"""
Sitemap Parser Utility
Parses XML sitemaps and extracts URLs for crawling using crawl4ai
"""
import logging
import re
from typing import List, Set
from xml.etree import ElementTree as ET
from urllib.parse import urljoin, urlparse

try:
    from crawl4ai import AsyncWebCrawler
    CRAWL4AI_AVAILABLE = True
except ImportError:
    CRAWL4AI_AVAILABLE = False

logger = logging.getLogger("website_crawling")


async def parse_sitemap(sitemap_content: str, base_url: str) -> List[str]:
    """
    Parse XML sitemap and extract all URLs.
    Handles standard sitemaps, sitemap indexes, and various namespace configurations.

    Args:
        sitemap_content: Raw XML content of the sitemap
        base_url: Base URL for resolving relative URLs

    Returns:
        List of URLs found in the sitemap
    """
    urls: Set[str] = set()

    try:
        # Parse XML with better error handling
        try:
            root = ET.fromstring(sitemap_content)
        except ET.ParseError as xml_error:
            logger.error(f"❌ XML parsing error: {xml_error}")
            logger.debug(f"Content preview: {sitemap_content[:200]}")
            
            # Try to fix common XML issues and retry
            try:
                # Remove any BOM and clean whitespace
                cleaned_content = sitemap_content.strip()
                if cleaned_content.startswith('<?xml'):
                    cleaned_content = cleaned_content.split('?>', 1)[1].strip()
                
                root = ET.fromstring(cleaned_content)
                logger.info("✅ Successfully parsed XML after cleaning")
            except ET.ParseError as retry_error:
                logger.error(f"❌ XML parsing failed even after cleaning: {retry_error}")
                return []
        
        logger.info(f"📄 Root element: {root.tag}")

        # Handle different sitemap namespaces
        namespaces = {
            'sm': 'http://www.sitemaps.org/schemas/sitemap/0.9',
            'xhtml': 'http://www.w3.org/1999/xhtml',
            'image': 'http://www.google.com/schemas/sitemap-image/1.1',
            'video': 'http://www.google.com/schemas/sitemap-video/1.1'
        }

        # Check if this is a sitemap index (contains other sitemaps)
        sitemap_elements = root.findall('.//sm:sitemap', namespaces)
        if sitemap_elements:
            logger.info(f"📋 Found sitemap index with {len(sitemap_elements)} sitemaps")
            # Extract URLs from sitemap index
            for sitemap in sitemap_elements:
                loc = sitemap.find('sm:loc', namespaces)
                if loc is not None and loc.text:
                    sitemap_url = loc.text.strip()
                    logger.debug(f"  → Sitemap: {sitemap_url}")
                    urls.add(sitemap_url)
        else:
            # This is a regular sitemap with URLs
            url_elements = root.findall('.//sm:url', namespaces)
            logger.info(f"📄 Found {len(url_elements)} URLs with namespace")

            for url_element in url_elements:
                loc = url_element.find('sm:loc', namespaces)
                if loc is not None and loc.text:
                    url = loc.text.strip()
                    # Make absolute URL
                    absolute_url = urljoin(base_url, url)
                    urls.add(absolute_url)

        # Also try without namespace (some sitemaps don't use it)
        if not urls:
            logger.info("🔄 Trying to parse sitemap without namespace...")

            # Try finding URLs without namespace
            for url_element in root.findall('.//url'):
                loc = url_element.find('loc')
                if loc is not None and loc.text:
                    url = loc.text.strip()
                    absolute_url = urljoin(base_url, url)
                    urls.add(absolute_url)

            if urls:
                logger.info(f"📄 Found {len(urls)} URLs without namespace")

            # Try finding sitemaps without namespace
            for sitemap_element in root.findall('.//sitemap'):
                loc = sitemap_element.find('loc')
                if loc is not None and loc.text:
                    sitemap_url = loc.text.strip()
                    urls.add(sitemap_url)

            if urls:
                logger.info(f"📋 Found {len(urls)} sitemaps without namespace")

        logger.info(f"✅ Extracted {len(urls)} total URLs from sitemap")
        return list(urls)

    except ET.ParseError as e:
        logger.error(f"❌ XML parsing error: {e}")
        logger.debug(f"Content preview: {sitemap_content[:200]}")
        return []
    except Exception as e:
        logger.error(f"❌ Error parsing sitemap: {e}", exc_info=True)
        return []


def is_sitemap_url(url: str) -> bool:
    """
    Check if a URL appears to be a sitemap.

    Args:
        url: URL to check

    Returns:
        True if URL appears to be a sitemap
    """
    url_lower = url.lower()
    return (
        url_lower.endswith('.xml') or
        'sitemap' in url_lower or
        url_lower.endswith('sitemap_index.xml') or
        url_lower.endswith('sitemap.xml')
    )


async def extract_urls_from_sitemap(url: str) -> List[str]:
    """
    Extract URLs from a sitemap using crawl4ai.
    Handles XML sitemaps and sitemap indexes.

    Args:
        url: Sitemap URL

    Returns:
        List of URLs found in the sitemap
    """
    if not CRAWL4AI_AVAILABLE:
        logger.error("❌ crawl4ai is not available for sitemap fetching")
        return []

    try:
        logger.info(f"📥 Fetching sitemap with crawl4ai: {url}")

        # Use crawl4ai to fetch the sitemap
        async with AsyncWebCrawler(verbose=False) as crawler:
            result = await crawler.arun(
                url=url,
                bypass_cache=True,
                wait_until='networkidle'
            )

            if not result.success:
                logger.error(f"❌ Failed to fetch sitemap: {result.error_message}")
                return []

            # Get the content (markdown or HTML)
            content = result.markdown or result.cleaned_html or result.html or ""

            if not content or not content.strip():
                logger.error(f"❌ Sitemap is empty at {url}")
                return []

            logger.info(f"📊 Sitemap size: {len(content)} bytes")

            # Try to parse as XML first
            urls = await parse_sitemap(content, url)

            # If XML parsing fails or returns no URLs, try extracting URLs from markdown/HTML
            if not urls:
                logger.info("🔄 Attempting to extract URLs from sitemap content using regex")
                # Extract URLs from the content using regex patterns
                # Matches both <loc>URL</loc> patterns and plain URLs
                url_patterns = [
                    r'<loc>\s*([^\<]+?)\s*</loc>',  # XML <loc> tags
                    r'https?://[^\s\<\>\{\}\[\]\(\)]+',  # Plain HTTP(S) URLs - more restrictive
                ]

                extracted_urls: Set[str] = set()
                for pattern in url_patterns:
                    matches = re.finditer(pattern, content, re.IGNORECASE)
                    for match in matches:
                        found_url = match.group(1) if match.lastindex else match.group(0)
                        found_url = found_url.strip()
                        if found_url:
                            # Validate URL format - ensure it's a proper URL without artifacts
                            # Check for common sitemap artifacts that indicate malformed URLs
                            if (re.search(r'[0-9]{4}-[0-9]{2}-[0-9]{2}T[0-9]{2}:[0-9]{2}:[0-9]{2}', found_url) or  # Timestamps
                                re.search(r'(monthly|weekly|daily|yearly|always)$', found_url) or      # Changefreq values
                                re.search(r'[0-9]+\.[0-9]+$', found_url) or                           # Priority values
                                re.search(r'[<>\{\}\[\]\(\)]', found_url)):                           # XML/HTML artifacts
                                logger.warning(f"⚠️ Skipping malformed URL with artifacts: {found_url[:100]}...")
                                continue
                            
                            # Make absolute URL
                            absolute_url = urljoin(url, found_url)
                            
                            # Final validation - ensure it's a proper HTTP/HTTPS URL
                            if re.match(r'^https?://[a-zA-Z0-9\.\-]+\.[a-zA-Z]{2,}', absolute_url):
                                extracted_urls.add(absolute_url)
                            else:
                                logger.warning(f"⚠️ Invalid URL format: {absolute_url[:100]}...")

                urls = list(extracted_urls)
                if urls:
                    logger.info(f"✅ Extracted {len(urls)} URLs from sitemap content using regex")

            if not urls:
                logger.warning(f"⚠️ No URLs extracted from sitemap at {url}")
                logger.debug(f"Sitemap content preview: {content[:500]}")

            return urls

    except Exception as e:
        logger.error(f"❌ Error fetching/parsing sitemap with crawl4ai: {e}", exc_info=True)
        return []


async def fetch_and_parse_sitemap(url: str) -> List[str]:
    """
    Fetch and crawl all pages from a sitemap using crawl4ai's BFS deep crawl strategy.
    This is a wrapper that extracts sitemap URLs and returns them for processing.

    Args:
        url: Sitemap URL

    Returns:
        List of URLs found in the sitemap (for compatibility with existing code)
    """
    return await extract_urls_from_sitemap(url)
