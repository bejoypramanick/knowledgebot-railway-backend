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


async def reconstruct_equations_in_text(text_content: str) -> str:
    """
    Use Gemini to detect and reconstruct broken equations in text.

    Docling breaks mathematical equations into separate lines/pieces.
    This function asks Gemini to identify and reconstruct them.

    Args:
        text_content: Markdown text that may contain broken equations

    Returns:
        Text with reconstructed equations in LaTeX format
    """
    if not text_content or len(text_content) < 50:
        return text_content

    logger.info("[EQUATIONS] Checking for broken equations in text...")

    try:
        genai_client = get_genai_client()
        if not genai_client:
            logger.warning("[EQUATIONS] Gemini client not available, skipping equation reconstruction")
            return text_content

        prompt = f"""You are a document processing expert. I have extracted text from a PDF using docling,
but mathematical equations have been broken into separate lines/pieces.

Please analyze the text below and:
1. Identify any broken or fragmented mathematical equations
2. Reconstruct them properly in LaTeX format (wrapped in $ for inline or $$ for display)
3. Keep all other text as-is
4. Return ONLY the corrected text, no explanations

Docling-extracted text:
{text_content}

Return the text with equations properly reconstructed in LaTeX format."""

        logger.info("[EQUATIONS] Sending text to Gemini for equation reconstruction...")

        loop = asyncio.get_event_loop()
        executor = ThreadPoolExecutor(max_workers=1)

        def call_gemini_equations():
            return genai_client.models.generate_content(
                model="gemini-1.5-flash",
                contents=prompt
            )

        response = await loop.run_in_executor(executor, call_gemini_equations)

        if response and response.text:
            reconstructed = response.text.strip()
            logger.info(f"✅ [EQUATIONS] Equations reconstructed ({len(reconstructed)} chars)")
            return reconstructed
        else:
            logger.warning("[EQUATIONS] Empty response from Gemini, returning original text")
            return text_content

    except Exception as e:
        logger.warning(f"⚠️ [EQUATIONS] Error reconstructing equations: {e}")
        logger.warning("[EQUATIONS] Returning original text without equation reconstruction")
        return text_content


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

    # Convert to markdown WITHOUT tables (they'll be formatted by Gemini)
    text = convert_docling_to_markdown(json_content, include_tables=False)

    # Clean up excess blank lines
    while '\n\n\n' in text:
        text = text.replace('\n\n\n', '\n\n')

    text = text.strip()
    logger.info(f"📝 Extracted text content: {len(text)} chars (NO raw tables - Gemini will format)")
    return text


def _build_table_prompt(table_text: str, table_number: int) -> str:
    """Build the Gemini prompt for formatting a single table."""
    return f"""You are a table analysis and formatting expert. I have extracted raw table data from a PDF using docling.

The data includes:
- Cell coordinates (bounding boxes) for alignment
- Cell positions (start_row_offset_idx, end_row_offset_idx, start_col_offset_idx, end_col_offset_idx)
- Text content for each cell
- Header flags (col_header, row_header) to identify structure
- Spans information for multi-row/multi-column cells

YOUR TASK:
1. Use the bounding box coordinates to determine correct row/column alignment
2. Handle cells that span multiple rows/columns properly (use their bounding boxes to infer position)
3. If table has nested structure (parent-child relationships):
   - FLATTEN the table so each row is independent
   - Include parent context in each nested row (use parent IDs/names as columns)
   - Make relationships explicit through shared parent identifiers
4. Create structured markdown format with:
   - Title showing table number {table_number}
   - Summary line describing table purpose, key columns, and data type
   - Column list (including parent context columns if nested)
   - Data rows in key-value format
5. Preserve all cell values exactly

OUTPUT FORMAT (Structured Markdown):

### Table: Table {table_number}
**Summary**: [Brief description of table contents, purpose, key columns, and data type]
**Columns**: [Comma-separated list of column headers]

**Row 1 (first row, 1st entry)**
- [Column 1]: [Value 1]
- [Column 2]: [Value 2]

**Row 2 (second row, 2nd entry)**
- [Column 1]: [Value 1]
- [Column 2]: [Value 2]

[Continue for all rows...]

NESTED TABLE HANDLING:
If the original table has nested/hierarchical structure, FLATTEN it like this:
- Each nested item becomes its own row
- Include parent identifiers (Parent ID, Parent Name, etc.)

REQUIREMENTS:
- Use markdown format, NOT JSON
- Include summary at top for context
- Use key-value pairs (-) for each column in each row
- Number each row with BOTH number AND spelled-out position
- List all columns in "Columns:" line
- Make it easy to read and search - explicit row naming helps RAG find specific rows
- Do NOT include raw docling metadata
- Do NOT include explanations, only the formatted markdown output

Docling raw table data (includes coordinates and spans):
{table_text}

Return the formatted table in the markdown KV format shown above."""


async def _format_single_table(genai_client, table: Dict[str, Any], table_number: int) -> Optional[str]:
    """Format a single table with Gemini. Returns markdown string or None on failure."""
    table_text = json.dumps(table, indent=2, ensure_ascii=False)
    num_rows = table.get('data', {}).get('num_rows', 0)
    num_cols = table.get('data', {}).get('num_cols', 0)
    logger.info(f"🤖 [GEMINI_TABLE_{table_number}] Formatting table: {num_rows} rows x {num_cols} cols, {len(table_text)} chars")

    prompt = _build_table_prompt(table_text, table_number)

    loop = asyncio.get_event_loop()
    executor = ThreadPoolExecutor(max_workers=1)

    def call_gemini():
        return genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

    try:
        response = await loop.run_in_executor(executor, call_gemini)

        if not response or not hasattr(response, 'text') or not response.text:
            logger.error(f"❌ [GEMINI_TABLE_{table_number}] Empty or invalid response")
            return None

        result = response.text.strip()
        logger.info(f"✅ [GEMINI_TABLE_{table_number}] Formatted: {len(result)} chars")
        return result

    except Exception as e:
        logger.error(f"❌ [GEMINI_TABLE_{table_number}] Failed: {e}")
        return None


async def format_tables_with_gemini(tables: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Send tables to Gemini one at a time for formatting.

    Processes each table individually to avoid overwhelming the API
    with large prompts when documents have many tables.

    Args:
        tables: List of table objects from docling

    Returns:
        Dictionary with formatted tables as markdown
    """
    logger.info("=" * 80)
    logger.info("🤖 [GEMINI_TABLES] === START TABLE FORMATTING WITH GEMINI ===")
    logger.info("=" * 80)

    if not tables:
        logger.warning("⚠️ [GEMINI_TABLES] No tables to format - returning empty")
        return {"tables": {}}

    logger.info(f"📊 [GEMINI_TABLES] Received {len(tables)} table(s) - processing one at a time")

    try:
        genai_client = get_genai_client()
        if not genai_client:
            logger.error("❌ [GEMINI_TABLES] Gemini client not available")
            return {"tables": {}, "error": "Gemini client not configured"}

        # Process each table individually
        all_markdown = []
        success_count = 0
        fail_count = 0

        for idx, table in enumerate(tables):
            table_number = idx + 1
            result = await _format_single_table(genai_client, table, table_number)
            if result:
                all_markdown.append(result)
                success_count += 1
            else:
                fail_count += 1

        logger.info(f"📊 [GEMINI_TABLES] Results: {success_count} succeeded, {fail_count} failed out of {len(tables)}")

        if not all_markdown:
            logger.error("❌ [GEMINI_TABLES] All tables failed to format")
            return {"tables_markdown": "", "error": "All tables failed"}

        # Combine all formatted tables
        combined_markdown = "\n\n".join(all_markdown)
        logger.info(f"✅ [GEMINI_TABLES] Combined markdown: {len(combined_markdown)} chars")

        logger.info("=" * 80)
        logger.info("✅ [GEMINI_TABLES] === END TABLE FORMATTING - SUCCESS ===")
        logger.info("=" * 80)
        return {
            "tables_markdown": combined_markdown,
            "format": "markdown_kv"
        }

    except Exception as e:
        logger.error(f"❌ [GEMINI_TABLES] Unexpected error: {e}")
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

    IMPORTANT: Only includes Gemini-formatted output (markdown KV format), NO raw docling data.
    This prevents duplication when sending to FileSearch.

    Args:
        text_content: Markdown text without tables
        formatted_tables: Dictionary with formatted tables from Gemini (markdown format)

    Returns:
        Merged markdown content (text + formatted tables markdown)
    """
    logger.info("=" * 80)
    logger.info("[MERGE] === MERGING TEXT + FORMATTED TABLES ===")
    logger.info("=" * 80)
    logger.info(f"[MERGE] Text content size: {len(text_content)} chars")

    # Add formatted tables section ONLY if Gemini successfully formatted them
    tables_section = ""

    if formatted_tables and "tables_markdown" in formatted_tables:
        tables_markdown = formatted_tables["tables_markdown"]
        if tables_markdown:
            logger.info(f"[MERGE] Adding formatted tables (markdown KV format)...")
            # Add section header and the markdown content
            tables_section = "\n\n---\n\n## Extracted Tables\n\n" + tables_markdown
            logger.info(f"✅ [MERGE] Tables section created: {len(tables_section)} chars")
        else:
            logger.warning("[MERGE] Formatted tables markdown is empty")
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
    logger.info(f"   ✓ Formatted tables (markdown): {len(tables_section)} chars")
    logger.info(f"   ✗ NO raw docling JSON included")
    logger.info(f"   ✓ Format: Markdown KV (optimized for RAG search)")
    logger.info("=" * 80)

    return merged


async def process_docling_content(json_content: str) -> str:
    """
    Unified function for processing docling JSON content.
    Both file worker and web worker use this to ensure identical processing.

    This function:
    1. Extracts tables from docling JSON
    2. Extracts text content from docling JSON
    3. Sends tables to Gemini for intelligent formatting
    4. Merges formatted tables back with text content

    Args:
        json_content: Raw JSON string from docling conversion

    Returns:
        Final markdown content with merged text and formatted tables
    """
    logger.info("=" * 80)
    logger.info("[DOCLING_PROCESS] === UNIFIED DOCLING PROCESSING ===")
    logger.info("=" * 80)

    # Inspect raw docling JSON structure before extraction
    try:
        import json as json_lib
        doc = json_lib.loads(json_content) if isinstance(json_content, str) else json_content
        if isinstance(doc, dict):
            logger.info("[DOCLING_PROCESS] === RAW JSON INSPECTION ===")
            texts_list = doc.get('texts', [])
            tables_list = doc.get('tables', [])
            groups_list = doc.get('groups', [])
            body = doc.get('body', {})
            children = body.get('children', [])

            logger.info(f"[DOCLING_PROCESS] Raw JSON counts:")
            logger.info(f"  texts: {len(texts_list)}")
            logger.info(f"  tables: {len(tables_list)}")
            logger.info(f"  groups: {len(groups_list)}")
            logger.info(f"  body.children: {len(children)}")

            # Show text types/labels
            if texts_list:
                labels = {}
                for t in texts_list:
                    label = t.get('label', 'unknown')
                    labels[label] = labels.get(label, 0) + 1
                logger.info(f"[DOCLING_PROCESS] Text labels: {labels}")

                # Show sample of each label type
                shown_labels = set()
                for t in texts_list:
                    label = t.get('label', 'unknown')
                    if label not in shown_labels:
                        text_val = t.get('text', '')[:100]
                        logger.info(f"[DOCLING_PROCESS]   {label} sample: {text_val}")
                        shown_labels.add(label)
    except Exception as e:
        logger.warning(f"[DOCLING_PROCESS] Could not inspect raw JSON: {e}")

    # 1. Extract tables
    logger.info("[DOCLING_PROCESS] Step 1: Extracting tables...")
    tables = extract_tables_from_docling_json(json_content)
    logger.info(f"[DOCLING_PROCESS] Found {len(tables)} tables")

    # 2. Extract text
    logger.info("[DOCLING_PROCESS] Step 2: Extracting text content...")
    text_content = extract_text_content_from_docling(json_content)
    logger.info(f"[DOCLING_PROCESS] Extracted {len(text_content)} chars of text")

    if not text_content:
        logger.warning("[DOCLING_PROCESS] ⚠️ NO TEXT CONTENT EXTRACTED!")
        logger.warning("[DOCLING_PROCESS] This is the root cause of missing content")
        logger.warning("[DOCLING_PROCESS] Check RAW JSON INSPECTION logs above to see what's in the JSON")
    else:
        logger.info(f"[DOCLING_PROCESS] Text sample (first 300 chars):")
        logger.info(f"[DOCLING_PROCESS] {text_content[:300]}...")

    # 3. Format tables with Gemini
    logger.info("[DOCLING_PROCESS] Step 3: Formatting tables with Gemini...")
    formatted_tables = await format_tables_with_gemini(tables)
    logger.info(f"[DOCLING_PROCESS] Tables formatting complete")

    # 4. Merge content
    logger.info("[DOCLING_PROCESS] Step 4: Merging text and formatted tables...")
    merged_content = merge_content_with_formatted_tables(text_content, formatted_tables)
    logger.info(f"[DOCLING_PROCESS] Merged content size: {len(merged_content)} chars")

    logger.info("=" * 80)
    logger.info(f"[DOCLING_PROCESS] === PROCESSING COMPLETE ===")
    logger.info("=" * 80)

    return merged_content
