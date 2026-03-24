"""
HTML cleaning utilities using Trafilatura for high-quality noise removal.
Designed to strip headers, footers, and ads while preserving table structures for RAG.
"""
import trafilatura
from typing import Optional
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("html_cleaner", "shared")

def clean_html_with_trafilatura(html_content: str, url: Optional[str] = None) -> str:
    """
    Extract the main content from HTML while removing boilerplate (headers, footers, ads).
    Uses Trafilatura with XML output to preserve table structure.
    
    Args:
        html_content: Raw HTML string.
        url: Optional URL for better context during extraction.
        
    Returns:
        A cleaned XML string containing the core content and tables, 
        or the original HTML if extraction fails.
    """
    if not html_content:
        return ""

    try:
        # Configuration for Trafilatura
        # include_tables=True is many-to-one with XML output
        # favor_precision=True helps in aggressively removing menus/ads
        extracted = trafilatura.extract(
            html_content,
            url=url,
            output_format='xml',
            include_tables=True,
            include_comments=False,
            include_images=False,
            no_fallback=False
        )
        
        if extracted:
            logger.info(f"✨ [HTML_CLEAN] Successfully cleaned HTML ({len(html_content)} -> {len(extracted)} bytes)")
            return extracted
            
        logger.warning("⚠️ [HTML_CLEAN] Trafilatura returned empty content, falling back to raw HTML")
        return html_content
        
    except Exception as e:
        logger.error(f"❌ [HTML_CLEAN] Error during Trafilatura extraction: {e}")
        return html_content
