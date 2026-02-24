"""
Use Gemini API to convert docling tables into meaningful JSON format.
Tables are extracted, sent to Gemini for intelligent formatting,
then merged back with non-table content.
"""
import json
import asyncio
from typing import Optional, Dict, Any, List
from concurrent.futures import ThreadPoolExecutor

from core.ai import get_genai_client
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("gemini_table_formatter", "docling")


def extract_tables_from_docling_json(json_content: str) -> List[Dict[str, Any]]:
    """
    Extract all tables from docling JSON output WITHOUT post-processing.

    Returns raw docling table data with all metadata:
    - Bounding boxes and coordinates
    - Cell positions (start/end row/col indices)
    - Text content
    - Header flags

    This raw metadata is sent to Gemini for intelligent alignment and formatting.

    Args:
        json_content: Raw JSON string from docling

    Returns:
        List of raw docling table objects with full metadata (bounding boxes, coordinates, etc.)
    """
    try:
        doc = json.loads(json_content)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse docling JSON for table extraction")
        return []

    tables = doc.get("tables", [])
    logger.info(f"📊 Extracted {len(tables)} raw table(s) from docling JSON (no post-processing)")

    # Log metadata available for Gemini
    for idx, table in enumerate(tables):
        data = table.get('data', {})
        num_rows = data.get('num_rows', 0)
        num_cols = data.get('num_cols', 0)
        cells = data.get('table_cells', [])
        bbox = table.get('bbox', None)
        logger.info(f"   Table {idx+1}: {num_rows}×{num_cols} cells={len(cells)} bbox={bbox}")

    return tables


def extract_text_content_from_docling(json_content: str) -> str:
    """
    Extract all text content (headings, paragraphs, lists) from docling JSON as markdown.

    Does NOT include tables - those are handled separately by Gemini.

    Args:
        json_content: Raw JSON string from docling

    Returns:
        Markdown string with text content only
    """
    try:
        doc = json.loads(json_content)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse docling JSON for text extraction")
        return ""

    from shared.docling_content_converter import convert_docling_to_markdown

    # Convert to markdown (includes tables temporarily)
    markdown_content = convert_docling_to_markdown(json_content)

    # Remove table sections (they start with ### Table)
    lines = markdown_content.split('\n')
    result_lines = []
    skip_table = False

    for line in lines:
        if line.startswith('### Table'):
            skip_table = True
            continue
        if skip_table and line.startswith('```'):
            skip_table = False
            continue
        if not skip_table:
            result_lines.append(line)

    # Clean up excess blank lines
    content = '\n'.join(result_lines)
    while '\n\n\n' in content:
        content = content.replace('\n\n\n', '\n\n')

    text = content.strip()
    logger.info(f"📝 Extracted text content: {len(text)} chars (no tables)")
    return text


async def format_tables_with_gemini(tables: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Send tables to Gemini model to convert into meaningful JSON format.

    Args:
        tables: List of table objects from docling

    Returns:
        Dictionary with formatted tables as JSON
    """
    logger.info("=" * 80)
    logger.info("🤖 [GEMINI_TABLES] === START TABLE FORMATTING WITH GEMINI ===")
    logger.info("=" * 80)

    if not tables:
        logger.warning("⚠️ [GEMINI_TABLES] No tables to format - returning empty")
        return {"tables": {}}

    logger.info(f"📊 [GEMINI_TABLES] Received {len(tables)} table(s) from docling")

    try:
        logger.info("[GEMINI_TABLES] Getting Gemini client...")
        genai_client = get_genai_client()
        if not genai_client:
            logger.error("❌ [GEMINI_TABLES] Gemini client not available")
            return {"tables": {}, "error": "Gemini client not configured"}

        logger.info("✅ [GEMINI_TABLES] Gemini client obtained")

        # Prepare table data for Gemini
        logger.info("[GEMINI_TABLES] Converting tables to JSON...")
        tables_text = json.dumps(tables, indent=2, ensure_ascii=False)
        logger.info(f"✅ [GEMINI_TABLES] Converted to JSON: {len(tables_text)} chars")

        logger.info(f"📊 [GEMINI_TABLES] Table statistics:")
        for idx, table in enumerate(tables):
            num_rows = table.get('data', {}).get('num_rows', 0)
            num_cols = table.get('data', {}).get('num_cols', 0)
            logger.info(f"   Table {idx+1}: {num_rows} rows × {num_cols} cols")

        # Create prompt for Gemini to format tables
        logger.info("[GEMINI_TABLES] Creating prompt for Gemini...")
        prompt = f"""You are a table analysis and formatting expert. I have extracted raw table data from a PDF using docling.

The data includes:
- Cell coordinates (bounding boxes) for alignment
- Cell positions (start_row_offset_idx, end_row_offset_idx, start_col_offset_idx, end_col_offset_idx)
- Text content for each cell
- Header flags (col_header, row_header) to identify structure
- Spans information for multi-row/multi-column cells

YOUR TASK:
1. Use the bounding box coordinates to determine correct row/column alignment
2. Handle cells that span multiple rows/columns properly (use their bounding boxes to infer position)
3. Create a meaningful JSON structure that represents the table logically
4. Add a "summary" field describing what the table contains (purpose, key columns, data type)
5. Preserve all cell values exactly

REQUIREMENTS:
- Return ONLY valid JSON
- Include "tables" key with list of formatted tables
- For each table include:
  * "summary": Brief description of table contents and purpose
  * "headers": Column headers identified from data
  * "rows": Properly aligned rows as array of objects with column headers as keys
- Do NOT include raw docling metadata in output
- Do NOT include explanations, only JSON

Docling raw table data (includes coordinates and spans):
{tables_text}

Return the formatted tables with summaries as valid JSON."""
        logger.info(f"✅ [GEMINI_TABLES] Prompt created: {len(prompt)} chars")

        # Call Gemini API in thread executor (synchronous API in async context)
        logger.info("[GEMINI_TABLES] Setting up executor for Gemini API call...")
        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(max_workers=1)

        def call_gemini():
            logger.info("[GEMINI_TABLES] >>> Calling genai_client.models.generate_content()...")
            try:
                result = genai_client.models.generate_content(
                    model="gemini-2.5-flash",
                    contents=prompt
                )
                logger.info(f"[GEMINI_TABLES] <<< API call returned successfully")
                return result
            except Exception as api_err:
                logger.error(f"[GEMINI_TABLES] <<< API call FAILED: {api_err}")
                raise

        logger.info("[GEMINI_TABLES] Running Gemini API in executor...")
        response = await loop.run_in_executor(executor, call_gemini)
        logger.info(f"✅ [GEMINI_TABLES] Executor returned response: {type(response)}")

        logger.info("[GEMINI_TABLES] Checking response...")
        if not response:
            logger.error("❌ [GEMINI_TABLES] Response is None/null")
            return {"tables": {}, "error": "Null response from Gemini"}

        logger.info(f"✅ [GEMINI_TABLES] Response object exists: {type(response).__name__}")

        if not hasattr(response, 'text'):
            logger.error(f"❌ [GEMINI_TABLES] Response has no 'text' attribute. Attributes: {dir(response)}")
            return {"tables": {}, "error": "Response missing text attribute"}

        if not response.text:
            logger.error(f"❌ [GEMINI_TABLES] Response text is empty/None")
            return {"tables": {}, "error": "Empty Gemini response text"}

        logger.info(f"✅ [GEMINI_TABLES] Got response text: {len(response.text)} chars")
        logger.info(f"📋 [GEMINI_TABLES_RESPONSE] Response preview (first 500 chars):")
        logger.info(response.text[:500])

        # Parse the JSON response
        logger.info("[GEMINI_TABLES] Parsing JSON response...")
        try:
            # Try to extract JSON from the response
            response_text = response.text.strip()
            logger.info(f"[GEMINI_TABLES] Response text length: {len(response_text)} chars")

            # If wrapped in markdown code block, extract it
            if response_text.startswith("```"):
                logger.info("[GEMINI_TABLES] Response wrapped in markdown code block - extracting JSON...")
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    response_text = response_text[json_start:json_end]
                    logger.info(f"[GEMINI_TABLES] Extracted JSON: {len(response_text)} chars")
                else:
                    logger.warning("[GEMINI_TABLES] Could not find JSON delimiters in code block")

            logger.info("[GEMINI_TABLES] Attempting to parse as JSON...")
            formatted = json.loads(response_text)
            logger.info(f"✅ [GEMINI_TABLES] Successfully parsed JSON")
            logger.info(f"📋 [GEMINI_TABLES] Parsed structure keys: {list(formatted.keys())}")

            if "tables" in formatted:
                logger.info(f"✅ [GEMINI_TABLES] Found 'tables' key with {len(formatted['tables'])} items")

            logger.info("=" * 80)
            logger.info("✅ [GEMINI_TABLES] === END TABLE FORMATTING - SUCCESS ===")
            logger.info("=" * 80)
            return formatted

        except json.JSONDecodeError as e:
            logger.error(f"❌ [GEMINI_TABLES] Failed to parse as JSON: {e}")
            logger.error(f"[GEMINI_TABLES] Full response text:")
            for line in response.text.split('\n')[:20]:  # Log first 20 lines
                logger.error(f"  {line}")
            return {"tables": {}, "error": f"Invalid JSON response: {str(e)}"}

    except Exception as e:
        logger.error(f"❌ [GEMINI_TABLES] Unexpected error: {e}")
        logger.error(f"[GEMINI_TABLES] Error type: {type(e).__name__}")
        import traceback
        logger.error(f"[GEMINI_TABLES] Traceback:\n{traceback.format_exc()}")
        logger.info("=" * 80)
        logger.info("❌ [GEMINI_TABLES] === END TABLE FORMATTING - ERROR ===")
        logger.info("=" * 80)
        return {"tables": {}, "error": str(e)}


def merge_content_with_formatted_tables(
    text_content: str,
    formatted_tables: Dict[str, Any]
) -> str:
    """
    Merge non-table text content with formatted tables into a single markdown document.

    IMPORTANT: Only includes Gemini-formatted output, NO raw docling data.
    This prevents duplication when sending to FileSearch.

    Args:
        text_content: Markdown text without tables
        formatted_tables: Dictionary with formatted tables from Gemini

    Returns:
        Merged markdown content (text + only formatted tables, NO raw docling JSON)
    """
    logger.info("=" * 80)
    logger.info("[MERGE] === MERGING TEXT + FORMATTED TABLES ===")
    logger.info("=" * 80)
    logger.info(f"[MERGE] Text content size: {len(text_content)} chars")

    # Add formatted tables section ONLY if Gemini successfully formatted them
    tables_section = ""

    if formatted_tables and "tables" in formatted_tables:
        tables_data = formatted_tables["tables"]
        if tables_data:
            logger.info(f"[MERGE] Adding formatted tables section...")
            tables_section = "\n\n## Formatted Tables\n\n```json\n"
            tables_section += json.dumps(tables_data, indent=2, ensure_ascii=False)
            tables_section += "\n```"
            logger.info(f"✅ [MERGE] Tables section created: {len(tables_section)} chars")
        else:
            logger.warning("[MERGE] Formatted tables is empty")
    elif formatted_tables.get("error"):
        logger.warning(f"[MERGE] ⚠️ Gemini formatting had error: {formatted_tables.get('error')}")
        logger.warning("[MERGE] Skipping formatted tables section - no output to include")

    # Combine text and formatted tables ONLY
    merged = text_content
    if tables_section:
        merged += tables_section

    logger.info("=" * 80)
    logger.info(f"✅ [MERGE] Final merged content: {len(merged)} chars")
    logger.info(f"   ✓ Text content: {len(text_content)} chars")
    logger.info(f"   ✓ Formatted tables: {len(tables_section)} chars")
    logger.info(f"   ✗ NO raw docling JSON included")
    logger.info("=" * 80)

    return merged
