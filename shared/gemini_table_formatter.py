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
   - Column summaries explaining the meaning of each column in natural language
   - Data rows in key-value format
5. Preserve all cell values exactly

OUTPUT FORMAT (Structured Markdown):

### Table: Table {table_number}
**Summary**: [Brief description of table contents, purpose, key columns, and data type]
**Columns**: [Comma-separated list of column headers]
**Column Summaries**:
- [Column 1]: [Brief natural language explanation of what this column represents and its meaning in the context of this table]
- [Column 2]: [Brief natural language explanation of what this column represents and its meaning in the context of this table]
- [Continue for all columns...]

**Row 1 (first row, 1st entry)**: [Natural language sentence that MUST include the VERBATIM column header name and VERBATIM cell value for every column, e.g., "Year: 1289, Population: 3,000, with an annual percentage change (±% p.a.) of +9.63%"]

**Row 2 (second row, 2nd entry)**: [Natural language sentence that MUST include the VERBATIM column header name and VERBATIM cell value for every column, e.g., "Year: 1348, Population: 7,000, showing a growth rate (±% p.a.) of +12.5%"]

[Continue for all rows...]

CRITICAL: VERBATIM COLUMN HEADERS AND CELL VALUES IN EVERY ROW
Each row description MUST contain:
1. The EXACT column header name as it appears in the table (verbatim, not paraphrased)
2. The EXACT cell value as it appears in the table (verbatim, not rounded or summarized)
This is essential because RAG search uses keyword matching to find specific rows.
If a user searches for a column name or cell value, it MUST appear verbatim in the row description.

NATURAL LANGUAGE FORMATTING EXAMPLES:
Instead of: **Row 2** | Year: 1289 | Population: 3,000 | ±% p.a.: +9.63%
Write as: **Row 2 (second row, 2nd entry)**: Year: 1289, Population: 3,000, with an annual percentage change (±% p.a.) of +9.63%

Instead of: **Row 3** | Battery: Li-ion | Capacity: 2500mAh | Cycles: 1000
Write as: **Row 3 (third row, 3rd entry)**: Battery: Li-ion, with a Capacity of 2500mAh and Cycles: 1000 charge cycles

Instead of: **Row 4** | Model: GPT-4 | Accuracy: 95.2% | Speed: 50ms
Write as: **Row 4 (fourth row, 4th entry)**: Model: GPT-4, achieving an Accuracy of 95.2% with a Speed of 50ms

NATURAL LANGUAGE GUIDELINES:
- Create flowing sentences that sound natural when read aloud
- Use connecting words like "with", "and", "showing", "achieving", "reaching"
- Incorporate units and context (e.g., "per year", "charge cycles", "response time")
- Make relationships between data points clear and meaningful
- MUST include the VERBATIM column header name for every data point (e.g., "Year:", "Population:", "Capacity:", "Model:")
- MUST include the VERBATIM cell value exactly as it appears (e.g., "3,000" not "three thousand", "Li-ion" not "lithium ion")
- Column headers act as keywords that enable RAG search to locate the correct row when users search by column name or value

NESTED TABLE HANDLING:
If the original table has nested/hierarchical structure, FLATTEN it like this:
- Each nested item becomes its own row
- Include parent identifiers (Parent ID, Parent Name, etc.)

REQUIREMENTS:
- Use markdown format, NOT JSON
- Include summary at top for context
- Include column summaries that explain each column's meaning in natural language phrases
- **CRITICAL: Each row MUST be a natural language sentence that includes VERBATIM column header names and VERBATIM cell values**
- **VERBATIM HEADERS**: Every column header must appear by name in the row description (e.g., "Year:", "Battery:", "Model:")
- **VERBATIM VALUES**: Every cell value must appear exactly as in the original table (e.g., "2500mAh" not "2.5Ah", "Li-ion" not "lithium ion")
- **RAG-SEARCHABLE**: Column headers and cell values serve as keywords for RAG search — omitting them means users cannot find the row by searching for a column name or value
- **NATURAL LANGUAGE FORMAT**: Transform data into readable sentences that flow naturally while preserving verbatim headers and values
- **CONTEXTUAL SENTENCES**: Create meaningful sentences that explain the relationship between data points
- Format each row as: **Row X (position)**: [Natural language sentence with verbatim column headers and cell values]
- Each sentence should incorporate all relevant data from the row in a flowing, readable manner
- Number each row with BOTH number AND spelled-out position
- List all columns in "Columns:" line
- Make it easy to read and search - explicit row naming AND verbatim column headers help RAG find specific rows
- Column summaries should be concise but descriptive, explaining what each column represents
- Do NOT include raw docling metadata
- Do NOT include explanations, only the formatted markdown output

Docling raw table data (includes coordinates and spans):
{table_text}

Return the formatted table in the markdown KV format shown above."""


# Max concurrent Gemini API calls (Tier 1: 150-300 RPM, safe with 5 parallel)
_GEMINI_TABLE_CONCURRENCY = 5


def _extract_first_cells_preview(table: Dict[str, Any], table_number: int) -> None:
    """Extract and log the first cell of each row for debugging purposes."""
    try:
        table_data = table.get('data', {})
        grid = table_data.get('grid', [])
        
        if not grid:
            logger.info(f"📋 [TABLE_{table_number}_PREVIEW] No grid data found")
            return
            
        logger.info(f"📋 [TABLE_{table_number}_PREVIEW] First cell of each row:")
        
        for row_idx, row in enumerate(grid):
            if row and len(row) > 0:
                first_cell = row[0]
                cell_text = first_cell.get('text', '').strip() if isinstance(first_cell, dict) else str(first_cell).strip()
                # Truncate long text for readability
                if len(cell_text) > 50:
                    cell_text = cell_text[:47] + "..."
                logger.info(f"📋 [TABLE_{table_number}_PREVIEW] Row {row_idx + 1}: '{cell_text}'")
            else:
                logger.info(f"📋 [TABLE_{table_number}_PREVIEW] Row {row_idx + 1}: <empty row>")
                
    except Exception as e:
        logger.warning(f"📋 [TABLE_{table_number}_PREVIEW] Failed to extract first cells: {e}")


async def _format_single_table(genai_client, table: Dict[str, Any], table_number: int,
                                semaphore: asyncio.Semaphore, executor: ThreadPoolExecutor) -> Optional[str]:
    """Format a single table with Gemini. Returns markdown string or None on failure."""
    table_text = json.dumps(table, indent=2, ensure_ascii=False)
    num_rows = table.get('data', {}).get('num_rows', 0)
    num_cols = table.get('data', {}).get('num_cols', 0)
    logger.info(f"🤖 [GEMINI_TABLE_{table_number}] Formatting table: {num_rows} rows x {num_cols} cols, {len(table_text)} chars")
    
    # Print first cell of each row for debugging
    _extract_first_cells_preview(table, table_number)

    prompt = _build_table_prompt(table_text, table_number)

    loop = asyncio.get_event_loop()

    def call_gemini():
        return genai_client.models.generate_content(
            model="gemini-2.5-flash",
            contents=prompt
        )

    try:
        async with semaphore:
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
    Send tables to Gemini in parallel for formatting.

    Processes tables concurrently (up to 5 at a time) using asyncio.gather
    with a semaphore to stay within Gemini Tier 1 rate limits (150-300 RPM).

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

    logger.info(f"📊 [GEMINI_TABLES] Received {len(tables)} table(s) - processing in parallel (max {_GEMINI_TABLE_CONCURRENCY} concurrent)")

    try:
        genai_client = get_genai_client()
        if not genai_client:
            logger.error("❌ [GEMINI_TABLES] Gemini client not available")
            return {"tables": {}, "error": "Gemini client not configured"}

        # Create semaphore and executor per invocation (safe across event loops)
        semaphore = asyncio.Semaphore(_GEMINI_TABLE_CONCURRENCY)
        executor = ThreadPoolExecutor(max_workers=_GEMINI_TABLE_CONCURRENCY)

        # Launch all tables in parallel, semaphore limits concurrency
        tasks = [
            _format_single_table(genai_client, table, idx + 1, semaphore, executor)
            for idx, table in enumerate(tables)
        ]
        results = await asyncio.gather(*tasks)

        # Collect results in order, filtering out failures
        all_markdown = []
        success_count = 0
        fail_count = 0
        for idx, result in enumerate(results):
            if result:
                all_markdown.append(result)
                success_count += 1
            else:
                fail_count += 1

        logger.info(f"📊 [GEMINI_TABLES] Results: {success_count} succeeded, {fail_count} failed out of {len(tables)}")

        if not all_markdown:
            logger.error("❌ [GEMINI_TABLES] All tables failed to format")
            return {"tables_markdown": "", "error": "All tables failed"}

        # Combine all formatted tables (order preserved from asyncio.gather)
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
