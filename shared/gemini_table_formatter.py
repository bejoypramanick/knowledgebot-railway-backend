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
3. If table has nested structure (parent-child relationships):
   - FLATTEN the table so each row is independent
   - Include parent context in each nested row (use parent IDs/names as columns)
   - Make relationships explicit through shared parent identifiers
4. Create structured markdown format for each table with:
   - Title showing table number/name
   - Summary line describing table purpose, key columns, and data type
   - Column list (including parent context columns if nested)
   - Data rows in key-value format
5. Preserve all cell values exactly

OUTPUT FORMAT (Structured Markdown):

### Table: [Table Name/Number]
**Summary**: [Brief description of table contents, purpose, key columns, and data type]
**Columns**: [Comma-separated list of column headers]

**Row 1**
- [Column 1]: [Value 1]
- [Column 2]: [Value 2]
- [Column 3]: [Value 3]

**Row 2**
- [Column 1]: [Value 1]
- [Column 2]: [Value 2]
- [Column 3]: [Value 3]

[Continue for all rows...]

NESTED TABLE HANDLING:
If the original table has nested/hierarchical structure, FLATTEN it like this:
- Each nested item becomes its own row
- Include parent identifiers (Parent ID, Parent Name, etc.)
- Example:
  **Row 1** (Parent Item)
  - ID: P1
  - Name: Parent A
  - Child ID: C1
  - Child Name: Child A1
  - Child Value: Val1

  **Row 2** (Another Child of Parent A)
  - ID: P1
  - Name: Parent A
  - Child ID: C2
  - Child Name: Child A2
  - Child Value: Val2

  **Row 3** (Parent Item B)
  - ID: P2
  - Name: Parent B
  - Child ID: C3
  - Child Name: Child B1
  - Child Value: Val3

REQUIREMENTS:
- Use markdown format, NOT JSON
- Include summary at top for context
- Use key-value pairs (-) for each column in each row
- Number each row clearly (**Row N**)
- List all columns in "Columns:" line
- Make it easy to read and search
- Do NOT include raw docling metadata
- Do NOT include explanations, only the formatted markdown output

Docling raw table data (includes coordinates and spans):
{tables_text}

Return the formatted tables in the markdown KV format shown above."""
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

        # Handle markdown response (structured KV format)
        logger.info("[GEMINI_TABLES] Processing markdown response...")
        try:
            response_text = response.text.strip()
            logger.info(f"[GEMINI_TABLES] Response text length: {len(response_text)} chars")

            # Response is now markdown format, not JSON
            # Return it wrapped in a structure for the merge function
            if not response_text:
                logger.error("❌ [GEMINI_TABLES] Empty response text")
                return {"tables_markdown": "", "error": "Empty response"}

            logger.info(f"✅ [GEMINI_TABLES] Received formatted markdown ({len(response_text)} chars)")
            logger.info("[GEMINI_TABLES] Markdown preview (first 500 chars):")
            logger.info(response_text[:500])

            # Return markdown content wrapped in expected format
            result = {
                "tables_markdown": response_text,
                "format": "markdown_kv"
            }

            logger.info("=" * 80)
            logger.info("✅ [GEMINI_TABLES] === END TABLE FORMATTING - SUCCESS ===")
            logger.info("=" * 80)
            return result

        except Exception as e:
            logger.error(f"❌ [GEMINI_TABLES] Error processing response: {e}")
            logger.error(f"[GEMINI_TABLES] Full response text:")
            for line in response.text.split('\n')[:20]:  # Log first 20 lines
                logger.error(f"  {line}")
            return {"tables_markdown": "", "error": str(e)}

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
