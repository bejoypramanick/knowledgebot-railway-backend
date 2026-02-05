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
                    urls.add(loc.text.strip())
        else:
            # This is a regular sitemap with URLs
            url_elements = root.findall('.//sm:url', namespaces)
            logger.info(f"📄 Found {len(url_elements)} URLs in sitemap")

            for url_element in url_elements:
                loc = url_element.find('sm:loc', namespaces)
                if loc is not None and loc.text:
                    url = loc.text.strip()
                    # Make absolute URL
                    absolute_url = urljoin(base_url, url)
                    urls.add(absolute_url)

        # Also try without namespace (some sitemaps don't use it)
        if not urls:
            logger.info("🔄 Trying to parse sitemap without namespace")
            for url_element in root.findall('.//url'):
                loc = url_element.find('loc')
                if loc is not None and loc.text:
                    url = loc.text.strip()
                    absolute_url = urljoin(base_url, url)
                    urls.add(absolute_url)

            for sitemap_element in root.findall('.//sitemap'):
                loc = sitemap_element.find('loc')
                if loc is not None and loc.text:
                    urls.add(loc.text.strip())

        logger.info(f"✅ Extracted {len(urls)} URLs from sitemap")
        return list(urls)

    except ET.ParseError as e:
        logger.error(f"❌ XML parsing error: {e}")
        return []
    except Exception as e:
        logger.error(f"❌ Error parsing sitemap: {e}")
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

    Args:
        url: Sitemap URL

    Returns:
        List of URLs found in the sitemap
    """
    try:
        import httpx

        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            logger.info(f"📥 Fetching sitemap from: {url}")
            response = await client.get(url)
            response.raise_for_status()

            # Check content type
            content_type = response.headers.get('content-type', '').lower()
            if 'xml' not in content_type and 'text' not in content_type:
                logger.warning(f"⚠️ Unexpected content type: {content_type}")

            # Parse the sitemap
            urls = await parse_sitemap(response.text, url)
            return urls

    except httpx.HTTPStatusError as e:
        logger.error(f"❌ HTTP error fetching sitemap: {e.response.status_code}")
        return []
    except Exception as e:
        logger.error(f"❌ Error fetching sitemap: {e}")
        return []
