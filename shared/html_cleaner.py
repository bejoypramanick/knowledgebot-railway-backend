"""
HTML cleaning utilities for web extraction.
Designed to strip obvious boilerplate while preserving rich page HTML for Kreuzberg.
"""
from typing import Optional
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("html_cleaner", "shared")


def clean_html_preserving_images(html_content: str, url: Optional[str] = None) -> str:
    """
    Use Trafilatura's permissive HTML extraction to strip boilerplate before
    Kreuzberg processing while keeping the remaining page as HTML.

    The goal here is intentionally broad retention: remove comments, menus,
    cookie banners, ads, and similar chrome, but preserve the main content
    structure, tables, images, and links so Kreuzberg can do the heavier
    downstream extraction and chunking work.
    """
    if not html_content:
        return ""

    try:
        from trafilatura import extract

        cleaned_html = extract(
            html_content,
            output_format="html",
            include_comments=False,
            include_images=True,
            include_links=False,
            include_tables=True,
            favor_recall=True,
            no_fallback=False,
            fast=False,
        )

        if not cleaned_html:
            logger.warning(
                f"⚠️ [HTML_CLEAN] Trafilatura returned no cleaned HTML; using raw HTML"
                f" | url={url or 'none'}"
                f" | input_chars={len(html_content)}"
            )
            return html_content

        if "<html" not in cleaned_html.lower():
            cleaned_html = f"<html><body>{cleaned_html}</body></html>"

        logger.info(
            f"✅ [HTML_CLEAN] Trafilatura cleaned HTML for Kreuzberg"
            f" | url={url or 'none'}"
            f" | input_chars={len(html_content)}"
            f" | output_chars={len(cleaned_html)}"
        )
        return cleaned_html
    except Exception as e:
        logger.warning(
            f"⚠️ [HTML_CLEAN] Trafilatura cleanup failed; using raw HTML"
            f" | url={url or 'none'}"
            f" | error={e}"
        )
        return html_content
