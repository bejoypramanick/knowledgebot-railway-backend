"""
HTML cleaning utilities using Trafilatura for high-quality noise removal.
Designed to strip headers, footers, and ads while preserving table structures for RAG.
"""
import trafilatura
from typing import Optional
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("html_cleaner", "shared")


def _minimal_dom_prune(html_content: str) -> str:
    """
    Minimal, structure-preserving HTML cleanup.

    Removes obvious boilerplate (ads/header/footer/nav/script/style) while
    preserving tables and images. This is intended for downstream extractors
    (Kreuzberg) which are layout-aware and benefit from intact HTML structure.
    """
    try:
        from lxml import html as lxml_html
        from lxml.etree import tostring
    except Exception:
        logger.warning("⚠️ [HTML_CLEAN] lxml not available; returning raw HTML")
        return html_content

    try:
        doc = lxml_html.fromstring(html_content)
    except Exception:
        return html_content

    # We do our own crawling with Crawl4AI, so hyperlinks are not needed for extraction.
    # Unwrap anchors to keep readable text while dropping href noise.
    try:
        for a in doc.xpath("//a"):
            a.drop_tag()
    except Exception:
        # Best-effort; if anchor unwrapping fails, continue with the rest of cleanup.
        pass

    # Remove non-content resources.
    for xpath in ("//script", "//style", "//noscript", "//iframe"):
        for node in doc.xpath(xpath):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)

    # Remove common boilerplate container tags.
    for tag in ("header", "footer", "nav", "aside"):
        for node in doc.findall(f".//{tag}"):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)

    # Remove obvious ad/cookie/subscribe blocks by class/id, avoiding table/img.
    junk_keywords = (
        "ad",
        "ads",
        "advert",
        "advertisement",
        "banner",
        "cookie",
        "consent",
        "newsletter",
        "subscribe",
        "promo",
        "sponsor",
        "sidebar",
        "modal",
        "popup",
    )

    def _looks_like_junk(value: Optional[str]) -> bool:
        if not value:
            return False
        v = value.lower()
        return any(k in v for k in junk_keywords)

    for node in doc.iter():
        if node.tag in ("table", "img"):
            continue
        if _looks_like_junk(node.get("id")) or _looks_like_junk(node.get("class")):
            parent = node.getparent()
            if parent is not None:
                parent.remove(node)

    cleaned = tostring(doc, encoding="unicode", method="html")
    return cleaned or html_content


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
        cleaned = _minimal_dom_prune(html_content)
        logger.info(f"✨ [HTML_CLEAN] Minimal DOM cleanup ({len(html_content)} -> {len(cleaned)} bytes)")
        return cleaned

    except Exception as e:
        logger.error(f"❌ [HTML_CLEAN] Error during Trafilatura extraction: {e}")
        return html_content
