"""
Hybrid content processing for web HTML:
- Trafilatura: Extract article text (designed for web content)
- Docling: Extract tables (designed for structured data)
- Gemini: Format tables intelligently
- Merge: Combine trafilatura text + Gemini-formatted tables (no duplication)
"""
import logging
from typing import Tuple, Optional

logger = logging.getLogger("hybrid_content_processor")


async def process_html_hybrid(
    html_content: str,
    docling_json: str
) -> str:
    """
    Process HTML using hybrid approach:
    1. Extract text with trafilatura (excludes tables)
    2. Extract tables with docling
    3. Format tables with Gemini
    4. Merge trafilatura text + Gemini-formatted tables
    
    Args:
        html_content: Raw HTML from crawl4ai
        docling_json: Docling JSON output (has tables)
        
    Returns:
        Final markdown with trafilatura text + formatted tables
    """
    logger.info("=" * 80)
    logger.info("[HYBRID] === HYBRID HTML PROCESSING ===")
    logger.info("=" * 80)
    
    # Step 1: Extract article text with trafilatura
    logger.info("[HYBRID] Step 1: Extracting article text with trafilatura (NO tables)...")
    text_content = extract_text_with_trafilatura(html_content)
    
    if not text_content:
        logger.error("[HYBRID] ❌ Trafilatura failed to extract text")
        raise Exception("Failed to extract text from HTML with trafilatura")
    
    logger.info(f"[HYBRID] ✅ Trafilatura extracted: {len(text_content)} chars")
    
    # Step 2: Extract tables with docling
    logger.info("[HYBRID] Step 2: Extracting tables from docling JSON...")
    from shared.gemini_table_formatter import extract_tables_from_docling_json
    tables = extract_tables_from_docling_json(docling_json)
    logger.info(f"[HYBRID] ✅ Docling found {len(tables)} tables")
    
    # Step 3: Format tables with Gemini
    if tables:
        logger.info(f"[HYBRID] Step 3: Formatting {len(tables)} tables with Gemini...")
        from shared.gemini_table_formatter import format_tables_with_gemini
        formatted_tables = await format_tables_with_gemini(tables)
        logger.info(f"[HYBRID] ✅ Tables formatted by Gemini")
    else:
        logger.info("[HYBRID] No tables to format")
        formatted_tables = {"tables_markdown": ""}
    
    # Step 4: Merge trafilatura text + Gemini-formatted tables
    logger.info("[HYBRID] Step 4: Merging trafilatura text + Gemini-formatted tables...")
    from shared.gemini_table_formatter import merge_content_with_formatted_tables
    final_content = merge_content_with_formatted_tables(text_content, formatted_tables)
    
    logger.info("=" * 80)
    logger.info(f"[HYBRID] ✅ === HYBRID PROCESSING COMPLETE ===")
    logger.info(f"[HYBRID] Final content: {len(final_content)} chars")
    logger.info(f"[HYBRID]   ✓ Trafilatura text: {len(text_content)} chars")
    logger.info(f"[HYBRID]   ✓ Docling tables: {len(tables)} tables")
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
