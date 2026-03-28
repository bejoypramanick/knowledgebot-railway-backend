"""
HTML cleaning utilities using Trafilatura for high-quality noise removal.
Designed to strip headers, footers, and ads while preserving table structures for RAG.
"""
import re
from typing import Optional
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("html_cleaner", "shared")


def _promote_table_captions(html_content: str) -> str:
    """Promote <caption> text into ordinary visible HTML before Trafilatura extraction."""
    def _replace_caption(match: re.Match) -> str:
        attrs = match.group(1) or ""
        caption_html = match.group(2) or ""
        caption_text = re.sub(r"<[^>]+>", " ", caption_html)
        caption_text = re.sub(r"\s+", " ", caption_text).strip()
        if not caption_text:
            return ""
        return (
            f'<p data-promoted-table-caption="true"{attrs}>'
            f"{caption_text}"
            f"</p>\n"
            f'<caption{attrs}>{caption_html}</caption>'
        )

    return re.sub(
        r"<caption([^>]*)>(.*?)</caption>",
        _replace_caption,
        html_content,
        flags=re.IGNORECASE | re.DOTALL,
    )


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

        raw_caption_present = "<caption" in html_content.lower()
        raw_caption_texts = re.findall(r"<caption[^>]*>(.*?)</caption>", html_content, flags=re.IGNORECASE | re.DOTALL)
        raw_caption_preview = " | ".join(
            re.sub(r"\s+", " ", caption).strip()[:120]
            for caption in raw_caption_texts[:3]
            if caption and re.sub(r"\s+", " ", caption).strip()
        )
        promoted_html = _promote_table_captions(html_content)

        # Deterministic configuration (no "try a bunch of kwargs" fallback logic).
        # Goal:
        # - Keep tables
        # - Keep images
        # - Strip hyperlinks (we crawl depth separately via Crawl4AI)
        # - Remove boilerplate like menus/sidebars/ads by extracting main content
        #
        # If these kwargs aren't supported by the deployed Trafilatura version, we
        # *fail loudly* so the deployment can be fixed (no silent degradation).
        cleaned = trafilatura.extract(
            promoted_html,
            favor_precision=True,
            include_comments=False,
            include_tables=True,
            include_links=False,
            no_fallback=False,
            output_format="html",
            url=url,
        )

        if not cleaned:
            # No fallback: return original HTML so downstream logs/S3 artifacts can
            # be inspected; the caller decides whether to fail the job.
            logger.warning("⚠️ [HTML_CLEAN] Trafilatura returned empty extraction; using original HTML")
            return html_content

        cleaned_caption_present = "<caption" in cleaned.lower()
        cleaned_contains_raw_caption_text = bool(
            raw_caption_preview and raw_caption_preview[:80].lower() in cleaned.lower()
        )
        promoted_caption_blocks = promoted_html.count('data-promoted-table-caption="true"')

        logger.info(f"✨ [HTML_CLEAN] Trafilatura extracted ({len(html_content)} -> {len(cleaned)} chars)")
        logger.info(
            f"🧭 [HTML_CAPTION_DIAG] url={url or 'none'} "
            f"raw_caption_present={'yes' if raw_caption_present else 'no'} "
            f"cleaned_caption_present={'yes' if cleaned_caption_present else 'no'} "
            f"cleaned_contains_caption_text={'yes' if cleaned_contains_raw_caption_text else 'no'} "
            f"raw_caption_preview='{raw_caption_preview or 'none'}' "
            f"promoted_caption_blocks={promoted_caption_blocks}"
        )
        return cleaned
    except Exception as e:
        logger.error(f"❌ [HTML_CLEAN] Error during Trafilatura extraction: {e}")
        return html_content
