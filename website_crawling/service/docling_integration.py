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
        # Create temporary HTML file for docling
        fd, temp_html_path = tempfile.mkstemp(suffix='.html')
        try:
            with os.fdopen(fd, 'w', encoding='utf-8') as f:
                f.write(html_content)

            # Prepare multipart form data
            with open(temp_html_path, 'rb') as f:
                files = {'file': (f'page-{page_url[-20:]}.html', f, 'text/html')}

                async with httpx.AsyncClient(timeout=timeout_seconds + 10) as client:
                    logger.info(
                        f"🌐 [DOCLING] Calling docling service for website: {page_url} "
                        f"(timeout={timeout_seconds}s)"
                    )

                    response = await client.post(
                        f"{settings.docling_service_url}/api/v1/docling/process",
                        files=files,
                        timeout=timeout_seconds
                    )

                    logger.info(f"🌐 [DOCLING] Response status: {response.status_code}")

                    if response.status_code == 200:
                        result = response.json()

                        if result.get("success"):
                            markdown_content = result.get("content")
                            metadata = result.get("metadata", {})

                            logger.info(
                                f"✅ [DOCLING] Successfully converted website HTML: "
                                f"{len(markdown_content)} chars"
                            )

                            return markdown_content, metadata
                        else:
                            error = result.get("error", "Unknown error")
                            # Check if this is a known docling limitation with HTML
                            if "ConversionStatus.FAILURE" in error or "HTML" in error:
                                logger.info(
                                    f"ℹ️ [DOCLING] HTML conversion not supported by docling for {page_url}. "
                                    f"This is expected - will use raw HTML extraction instead."
                                )
                            else:
                                logger.warning(
                                    f"⚠️ [DOCLING] HTML conversion failed for {page_url}: {error}"
                                )
                            return None, {"error": error, "expected": "ConversionStatus.FAILURE" in error}
                    else:
                        error_msg = f"HTTP {response.status_code}: {response.text}"
                        logger.warning(f"⚠️ [DOCLING] Request failed for {page_url}: {error_msg}")
                        return None, {"error": error_msg}

        finally:
            # Cleanup temp file
            if os.path.exists(temp_html_path):
                try:
                    os.unlink(temp_html_path)
                except:
                    pass

    except asyncio.TimeoutError:
        logger.warning(
            f"⚠️ [DOCLING] Timeout converting HTML for {page_url} "
            f"(timeout={timeout_seconds}s)"
        )
        return None, {"error": "Docling processing timeout"}

    except Exception as e:
        logger.warning(
            f"⚠️ [DOCLING] Error calling docling service for {page_url}: {e}"
        )
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
