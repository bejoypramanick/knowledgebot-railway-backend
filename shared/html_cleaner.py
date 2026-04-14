"""
HTML cleaning utilities using Trafilatura for high-quality noise removal.
Designed to strip headers, footers, and ads while preserving table structures for RAG.
"""
import re
from typing import Optional
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("html_cleaner", "shared")


def _restore_table_captions(cleaned_html: str, raw_captions: list[str]) -> str:
    """Reinsert raw <caption> tags into cleaned tables when Trafilatura drops them."""
    if not cleaned_html or not raw_captions or "<table" not in cleaned_html.lower():
        return cleaned_html

    captions_iter = iter(raw_captions)

    def _replace_table(match: re.Match) -> str:
        table_open = match.group(0)
        if "<caption" in table_open.lower():
            return table_open
        caption_tag = next(captions_iter, "")
        if not caption_tag:
            return table_open
        return f"{table_open}{caption_tag}"

    return re.sub(r"<table\b[^>]*>", _replace_table, cleaned_html, flags=re.IGNORECASE)


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
        raw_caption_tags = re.findall(r"(<caption[^>]*>.*?</caption>)", html_content, flags=re.IGNORECASE | re.DOTALL)

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

        restored_cleaned = _restore_table_captions(cleaned, raw_caption_tags)

        cleaned_caption_present = "<caption" in restored_cleaned.lower()
        cleaned_contains_raw_caption_text = bool(
            raw_caption_preview and raw_caption_preview[:80].lower() in restored_cleaned.lower()
        )
        restored_caption_blocks = restored_cleaned.lower().count("<caption")

        logger.info(f"✨ [HTML_CLEAN] Trafilatura extracted ({len(html_content)} -> {len(restored_cleaned)} chars)")
        logger.info(
            f"🧭 [HTML_CAPTION_DIAG] url={url or 'none'} "
            f"raw_caption_present={'yes' if raw_caption_present else 'no'} "
            f"cleaned_caption_present={'yes' if cleaned_caption_present else 'no'} "
            f"cleaned_contains_caption_text={'yes' if cleaned_contains_raw_caption_text else 'no'} "
            f"raw_caption_preview='{raw_caption_preview or 'none'}' "
            f"restored_caption_blocks={restored_caption_blocks}"
        )
        return restored_cleaned
    except Exception as e:
        logger.error(f"❌ [HTML_CLEAN] Error during Trafilatura extraction: {e}")
        return html_content
