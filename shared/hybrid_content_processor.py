"""
Hybrid content processing for web HTML has been simplified.
Kreuzberg natively extracts HTML into Markdown, so we just run the Gemini table 
formatter on the Kreuzberg Markdown output.
"""
import logging
from typing import Tuple, Optional, List, Dict, Any
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("hybrid_content_processor", "shared")


async def process_html_hybrid(
    html_content: str,
    kreuzberg_markdown: str,
    source_id: Optional[str] = None,
    source_name: Optional[str] = None,
    source_type: str = "website"
) -> Tuple[str, List[Dict[str, Any]], int]:
    """
    Process HTML:
    Since Kreuzberg already extracts everything to Markdown perfectly,
    we just pass it to the Gemini table formatter to ensure tables get natural language descriptions.

    Args:
        html_content: Original HTML (kept for signature compatibility)
        kreuzberg_markdown: Markdown output from Kreuzberg
        source_id: Optional ID of the source (website_id)
        source_name: Optional name/URL of the source
        source_type: Type of source (default 'website')

    Returns:
        Tuple of (final_markdown, tables_metadata, total_pages)
    """
    logger.info("=" * 80)
    logger.info(f"[HYBRID] === HYBRID HTML PROCESSING ({source_name}) ===")
    logger.info("=" * 80)

    from shared.gemini_table_formatter import process_extracted_markdown

    logger.info("[HYBRID] Processing Kreuzberg Markdown to format tables with Gemini...")
    final_content, tables_metadata = await process_extracted_markdown(
        kreuzberg_markdown,
        source_id=source_id,
        source_name=source_name,
        source_type=source_type
    )

    logger.info("=" * 80)
    logger.info(f"[HYBRID] ✅ === HYBRID PROCESSING COMPLETE ===")
    logger.info(f"[HYBRID] Final content: {len(final_content)} chars")
    logger.info(f"[HYBRID]   ✓ Processed {len(tables_metadata)} tables")
    logger.info("=" * 80)

    return final_content, tables_metadata, 0
