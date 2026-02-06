"""Docling service integration for website crawling."""
import asyncio
import logging
import os
import tempfile
from typing import Optional, Tuple

import httpx

from website_crawling.core.config import settings

logger = logging.getLogger("website_crawling")

# Supported file types for docling processing
SUPPORTED_FILE_TYPES = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt",
    ".xlsx", ".xls", ".html", ".htm"
}


async def process_html_with_docling(
    html_content: str,
    page_url: str,
    timeout_seconds: Optional[int] = None
) -> Tuple[Optional[str], dict]:
    """
    Call docling service to convert HTML to markdown.

    Args:
        html_content: HTML content to convert
        page_url: URL of the page (for reference)
        timeout_seconds: Request timeout in seconds

    Returns:
        Tuple of (markdown_content, metadata) or (None, error_dict) on failure
    """
    if timeout_seconds is None:
        timeout_seconds = settings.docling_website_timeout_seconds

    try:
        logger.info(f"🌐 [ROUTING] Routing HTML content for {page_url} to strict HTML pipeline")
        
        from shared.html_processor import extract_content_from_html
        markdown_content, html_metadata = extract_content_from_html(html_content=html_content)
        
        if markdown_content:
            logger.info(f"✅ [HTML] Successfully extracted {len(markdown_content)} characters using trafilatura")
            return markdown_content, html_metadata
        else:
            error_msg = html_metadata.get("error", "HTML extraction failed")
            logger.error(f"❌ [HTML] Extraction failed for {page_url}: {error_msg}")
            return None, {"error": error_msg}

    except Exception as e:
        logger.error(f"❌ [HTML] Error in HTML pipeline for {page_url}: {e}")
        return None, {"error": str(e)}


async def should_use_docling_for_website() -> bool:
    """
    Determine if docling should be used for website crawling.

    Checks:
    1. DOCLING_ENABLED_FOR_WEBSITES environment variable
    2. Docling service URL is configured

    Returns:
        True if docling should be used, False otherwise
    """
    # Check if docling is enabled for websites
    if not settings.docling_enabled_for_websites:
        return False

    # Check if docling service URL is configured
    if not settings.docling_service_url:
        return False

    return True
