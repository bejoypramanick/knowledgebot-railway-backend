"""
HTML cleaning utilities using Trafilatura for high-quality noise removal.
Designed to strip headers, footers, and ads while preserving table structures for RAG.
"""
import re
from typing import Optional
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("html_cleaner", "shared")


def clean_html_with_trafilatura(html_content: str, url: Optional[str] = None) -> str:
    """
    Extract the main content from HTML (Currently Bypassed).
    Returns the original HTML so Kreuzberg can handle extraction.
    """
    if not html_content:
        return ""

    # BYPASS: Trafilatura cleaning is bypassed for now to test raw HTML extraction via KREUZBERG.
    logger.info(f"⏭️ [HTML_CLEAN] Trafilatura Bypassed (using raw HTML) | url={url or 'none'}")
    return html_content
