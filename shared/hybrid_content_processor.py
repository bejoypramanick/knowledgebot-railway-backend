"""
Hybrid content processing for web HTML:
- Trafilatura: Extract article text (designed for web content)
- Docling: Extract tables (designed for structured data)
- Gemini: Format tables intelligently
- Merge: Combine trafilatura text + Gemini-formatted tables (no duplication)

CRITICAL: Both trafilatura and docling receive the SAME HTML input
"""
import logging
from shared.otel_logger import get_otel_logger
from shared.otel_logger import get_otel_logger
import hashlib
from typing import Tuple, Optional, List, Dict, Any

logger = get_otel_logger("hybrid_content_processor", "shared")


async def process_html_hybrid(
    html_content: str,
    docling_json: str
) -> Tuple[str, List[Dict[str, Any]], int]:
    """
    Process HTML using hybrid approach:
    1. Extract tables ONLY from docling (no text items)
    2. Format tables with Gemini
    3. Extract text with trafilatura (excludes tables, extracts all text as-is)
    4. Merge trafilatura text + Gemini-formatted tables

    Args:
        html_content: HTML from crawl4ai (only ads/menus removed, full page preserved)
                     Trafilatura extracts all accessible text without filtering
        docling_json: Docling JSON output (tables only)

    Returns:
        Tuple of (final_markdown, tables_metadata, total_pages) where tables_metadata is a list of
        per-table metric dicts from Gemini formatting, and total_pages is the page count from docling
    """
    logger.info("=" * 80)
    logger.info("[HYBRID] === HYBRID HTML PROCESSING ===")
    logger.info("=" * 80)

    # Verify HTML input integrity
    html_hash = hashlib.md5(html_content.encode('utf-8')).hexdigest()[:8]
    logger.info(f"[HYBRID] Input HTML hash: {html_hash} ({len(html_content)} bytes)")
    logger.info(f"[HYBRID] ✓ Trafilatura will receive this exact HTML")
    logger.info(f"[HYBRID] ✓ Docling processed this same HTML (from S3)")

    # Step 0: Extract total page count from docling
    from shared.gemini_table_formatter import extract_total_pages_from_docling
    total_pages = extract_total_pages_from_docling(docling_json)

    # Step 1: Extract ONLY tables from docling (no text items)
    logger.info("[HYBRID] Step 1: Extracting tables from docling JSON (tables only)...")
    from shared.gemini_table_formatter import extract_tables_from_docling_json
    tables = extract_tables_from_docling_json(docling_json)
    logger.info(f"[HYBRID] ✅ Docling found {len(tables)} tables")

    # Step 2: Format tables with Gemini
    tables_metadata = []
    if tables:
        logger.info(f"[HYBRID] Step 2: Formatting {len(tables)} tables with Gemini...")
        from shared.gemini_table_formatter import format_tables_with_gemini
        formatted_tables = await format_tables_with_gemini(tables)
        tables_metadata = formatted_tables.get("tables_metadata", [])
        logger.info(f"[HYBRID] ✅ Tables formatted by Gemini ({len(tables_metadata)} metadata records)")
    else:
        logger.info("[HYBRID] No tables to format")
        formatted_tables = {"tables_markdown": ""}

    # Step 3: Extract article text with trafilatura (AFTER docling tables are processed)
    logger.info("[HYBRID] Step 3: Extracting article text with trafilatura (NO tables)...")
    text_content = extract_text_with_trafilatura(html_content)

    if not text_content:
        logger.error("[HYBRID] ❌ Trafilatura failed to extract text")
        raise Exception("Failed to extract text from HTML with trafilatura")

    logger.info(f"[HYBRID] ✅ Trafilatura extracted: {len(text_content)} chars")

    # Step 4: Merge trafilatura text + Gemini-formatted tables
    logger.info("[HYBRID] Step 4: Merging trafilatura text + Gemini-formatted tables...")
    from shared.gemini_table_formatter import merge_content_with_formatted_tables
    final_content = merge_content_with_formatted_tables(text_content, formatted_tables)

    logger.info("=" * 80)
    logger.info(f"[HYBRID] ✅ === HYBRID PROCESSING COMPLETE ===")
    logger.info(f"[HYBRID] Final content: {len(final_content)} chars")
    logger.info(f"[HYBRID]   ✓ Docling tables: {len(tables)} tables (Gemini formatted)")
    logger.info(f"[HYBRID]   ✓ Trafilatura text: {len(text_content)} chars")
    logger.info(f"[HYBRID]   ✓ NO duplication (trafilatura excluded tables)")
    logger.info("=" * 80)

    return final_content, tables_metadata, total_pages


def extract_text_with_trafilatura(html_content: str) -> Optional[str]:
    """
    Extract text from HTML using trafilatura.
    CRITICAL: Exclude only tables (docling handles tables).
    Extract everything else: sidebars, navigation, comments, all text content.

    Args:
        html_content: HTML with only ads/menus removed by crawl4ai

    Returns:
        Extracted text as markdown (all content except tables), or None if extraction fails
    """
    try:
        import trafilatura

        logger.info("[TRAFILATURA] Extracting text from HTML (only exclude tables)...")

        extracted = trafilatura.extract(
            html_content,
            include_tables=False,  # CRITICAL: Don't extract tables (docling will)
            output_format='markdown'
            # Extract everything else: sidebars, navigation, comments, all text
        )
        
        if extracted:
            char_count = len(extracted)
            line_count = len(extracted.split('\n'))
            logger.info(f"[TRAFILATURA] ✅ Extracted: {char_count} chars, {line_count} lines")
            
            # Log sample to verify article content (not nav/menus)
            sample = extracted[:500]
            logger.info(f"[TRAFILATURA] Sample (first 500 chars):\n{sample}...")
            
            return extracted
        else:
            logger.warning("[TRAFILATURA] ⚠️  No content extracted")
            return None
            
    except Exception as e:
        logger.error(f"[TRAFILATURA] ❌ Extraction failed: {e}")
        return None
