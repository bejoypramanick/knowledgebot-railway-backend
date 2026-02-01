from typing import List
import logging
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

def extract_links_from_result(result, base_url: str) -> List[str]:
    """Extract internal links from crawl result for further crawling."""
    links = []

    try:
        parsed_base = urlparse(base_url)
        base_domain = parsed_base.netloc

        if hasattr(result, 'links') and result.links:
            if isinstance(result.links, dict):
                # Crawl4AI 0.7.x format
                if 'internal' in result.links:
                    internal_links = result.links['internal']
                    if isinstance(internal_links, list):
                        for link in internal_links:
                            href = link.get('href', link) if isinstance(link, dict) else link
                            if isinstance(href, str) and href.startswith(('http://', 'https://')):
                                try:
                                    parsed_link = urlparse(href)
                                    # Only include links from same domain
                                    if parsed_link.netloc == base_domain:
                                        links.append(href)
                                except:
                                    continue
            elif isinstance(result.links, list):
                # Alternative format
                for link in result.links:
                    if isinstance(link, str) and link.startswith(('http://', 'https://')):
                        try:
                            parsed_link = urlparse(link)
                            if parsed_link.netloc == base_domain:
                                links.append(link)
                        except:
                            continue

    except Exception as e:
        logger.warning(f"Error extracting links from result: {e}")

    return links[:10]  # Limit to prevent explosion
