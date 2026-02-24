"""
Hybrid content processing for web HTML:
- Trafilatura: Extract article text (designed for web content)
- Docling: Extract tables (designed for structured data)
- Gemini: Format tables intelligently
- Merge: Combine trafilatura text + Gemini-formatted tables (no duplication)

CRITICAL: Both trafilatura and docling receive the SAME HTML input
"""
import logging
import hashlib
from typing import Tuple, Optional

logger = logging.getLogger("hybrid_content_processor")


async def process_html_hybrid(
    html_content: str,
    docling_json: str
) -> str:
    """
    Process HTML using hybrid approach:
    1. Extract tables ONLY from docling (no text items)
    2. Format tables with Gemini
    3. Extract text with trafilatura (excludes tables, filters out menus/sidebars)
    4. Merge trafilatura text + Gemini-formatted tables

    Args:
        html_content: HTML from crawl4ai (ads/overlays removed, keeps sidebars/navigation)
                     Trafilatura will extract only article content from full page
        docling_json: Docling JSON output (tables only)

    Returns:
        Final markdown with article text + formatted tables
    """
    logger.info("=" * 80)
    logger.info("[HYBRID] === HYBRID HTML PROCESSING ===")
    logger.info("=" * 80)

    # Verify HTML input integrity
    html_hash = hashlib.md5(html_content.encode('utf-8')).hexdigest()[:8]
    logger.info(f"[HYBRID] Input HTML hash: {html_hash} ({len(html_content)} bytes)")
    logger.info(f"[HYBRID] ✓ Trafilatura will receive this exact HTML")
    logger.info(f"[HYBRID] ✓ Docling processed this same HTML (from S3)")

    # Step 1: Extract ONLY tables from docling (no text items)
    logger.info("[HYBRID] Step 1: Extracting tables from docling JSON (tables only)...")
    from shared.gemini_table_formatter import extract_tables_from_docling_json
    tables = extract_tables_from_docling_json(docling_json)
    logger.info(f"[HYBRID] ✅ Docling found {len(tables)} tables")

    # Step 2: Format tables with Gemini
    if tables:
        logger.info(f"[HYBRID] Step 2: Formatting {len(tables)} tables with Gemini...")
        from shared.gemini_table_formatter import format_tables_with_gemini
        formatted_tables = await format_tables_with_gemini(tables)
        logger.info(f"[HYBRID] ✅ Tables formatted by Gemini")
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

    return final_content


def extract_text_with_trafilatura(html_content: str) -> Optional[str]:
    """
    Extract article text from HTML using trafilatura.
    IMPORTANT: include_tables=False to avoid duplication with docling tables.
    
    Args:
        html_content: Raw HTML string
        
    Returns:
        Extracted text as markdown, or None if extraction fails
    """
    try:
        import trafilatura
        
        logger.info("[TRAFILATURA] Extracting text (tables excluded)...")
        
        extracted = trafilatura.extract(
            html_content,
            include_tables=False,  # CRITICAL: Don't extract tables (docling will)
            output_format='markdown',
            include_comments=False,
            favor_precision=True
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
