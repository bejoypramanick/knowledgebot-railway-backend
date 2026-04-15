"""
HTML cleaning utilities using Trafilatura for high-quality noise removal.
Designed to strip headers, footers, and ads while preserving table structures for RAG.
"""
from typing import Optional
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("html_cleaner", "shared")


def clean_html_with_trafilatura(html_content: str, url: Optional[str] = None) -> str:
    """
    Extract the main content from HTML before Kreuzberg extraction.

    Trafilatura removes common boilerplate such as headers, navigation menus,
    footers, cookie banners, ads, and sidebars. Links are kept as visible text
    only so downstream markdown does not preserve noisy URL wrappers.
    """
    if not html_content:
        return ""

    try:
        import trafilatura

        extract_kwargs = {
            "favor_precision": False,
            "include_comments": False,
            "include_tables": True,
            "include_links": False,
            "no_fallback": False,
            "output_format": "html",
            "url": url,
        }

        try:
            extracted_html = trafilatura.extract(
                html_content,
                include_images=True,
                **extract_kwargs,
            )
        except TypeError:
            extracted_html = trafilatura.extract(html_content, **extract_kwargs)

        if extracted_html and extracted_html.strip():
            logger.info(
                f"✅ [HTML_CLEAN] Trafilatura extracted main content"
                f" | url={url or 'none'}"
                f" | input_chars={len(html_content)}"
                f" | output_chars={len(extracted_html)}"
            )
            return extracted_html

        logger.warning(
            f"⚠️ [HTML_CLEAN] Trafilatura returned empty content; using raw HTML"
            f" | url={url or 'none'}"
        )
        return html_content
    except Exception as e:
        logger.warning(
            f"⚠️ [HTML_CLEAN] Trafilatura failed; using raw HTML"
            f" | url={url or 'none'}"
            f" | error={e}"
        )
        return html_content
