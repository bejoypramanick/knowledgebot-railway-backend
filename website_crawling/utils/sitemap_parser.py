"""
Sitemap Parser Utility
Parses XML sitemaps and extracts URLs for crawling
"""
import logging
from typing import List, Set
from xml.etree import ElementTree as ET
from urllib.parse import urljoin, urlparse

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
        # Parse XML
        root = ET.fromstring(sitemap_content)
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


async def fetch_and_parse_sitemap(url: str) -> List[str]:
    """
    Fetch and parse a sitemap from a URL.
    Handles standard sitemaps, sitemap indexes, and gzipped content.

    Args:
        url: Sitemap URL

    Returns:
        List of URLs found in the sitemap
    """
    try:
        import httpx
        import gzip

        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            logger.info(f"📥 Fetching sitemap from: {url}")
            response = await client.get(url)
            response.raise_for_status()

            # Check content type
            content_type = response.headers.get('content-type', '').lower()
            logger.info(f"📋 Sitemap content-type: {content_type}")

            # Handle gzipped content
            content = response.content
            if content_type.startswith('application/x-gzip') or url.lower().endswith('.gz'):
                logger.info("🔧 Decompressing gzipped sitemap")
                try:
                    content = gzip.decompress(content)
                except Exception as gz_error:
                    logger.warning(f"⚠️ Failed to decompress gzip: {gz_error}")
                    # Try without decompression
                    content = response.content

            # Decode content
            try:
                content_text = content.decode('utf-8')
            except UnicodeDecodeError:
                logger.warning("⚠️ UTF-8 decode failed, trying latin-1")
                content_text = content.decode('latin-1')

            if not content_text.strip():
                logger.error(f"❌ Sitemap is empty at {url}")
                return []

            logger.info(f"📊 Sitemap size: {len(content_text)} bytes")

            # Parse the sitemap
            urls = await parse_sitemap(content_text, url)

            if not urls:
                logger.warning(f"⚠️ No URLs extracted from sitemap at {url}")
                logger.debug(f"Sitemap content preview: {content_text[:500]}")

            return urls

    except httpx.HTTPStatusError as e:
        logger.error(f"❌ HTTP error fetching sitemap: {e.response.status_code} - {e.response.text[:200]}")
        return []
    except Exception as e:
        logger.error(f"❌ Error fetching sitemap: {e}", exc_info=True)
        return []
