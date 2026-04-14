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
    Extract the main content from HTML while removing boilerplate (headers, footers, ads).
    Uses Trafilatura extraction (no custom extraction logic).
    
    Args:
        html_content: Raw HTML string.
        url: Optional URL for better context during extraction.
        
    Returns:
        A cleaned HTML snippet containing the core content (tables + images preserved),
        or the original HTML if extraction fails.
    """
    if not html_content:
        return ""

    try:
        import trafilatura

        # Deterministic configuration (no "try a bunch of kwargs" fallback logic).
        # Goal:
        # - Keep everything "as is" within the main content block
        # - Specifically remove: ads, menus, comments, footers (boilerplate)
        # - Preserve: tables, links, images, formatting
        # - Favor recall over precision to avoid aggressive pruning
        cleaned = trafilatura.extract(
            html_content,
            favor_precision=False,  # Keep more content (recall > precision)
            include_comments=False, # Explicitly requested to remove comments
            include_tables=True,
            include_links=True,     # Keep links within content
            include_formatting=True, # Keep subheadings, bold, etc.
            include_images=True,     # Keep images
            no_fallback=False,
            output_format="html",
            url=url,
        )

        if not cleaned:
            # No fallback: return original HTML so downstream logs/S3 artifacts can
            # be inspected; the caller decides whether to fail the job.
            logger.warning("⚠️ [HTML_CLEAN] Trafilatura returned empty extraction; using original HTML")
            return html_content

        logger.info(f"✨ [HTML_CLEAN] Trafilatura extracted ({len(html_content)} -> {len(cleaned)} chars) | url={url or 'none'}")
        return cleaned
    except Exception as e:
        logger.error(f"❌ [HTML_CLEAN] Error during Trafilatura extraction: {e}")
        return html_content
