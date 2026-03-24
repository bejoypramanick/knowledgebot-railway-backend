"""
Use Gemini API to convert markdown tables into meaningful JSON/Markdown format.
Tables are extracted from markdown text, sent to Gemini for intelligent formatting,
then replaced back into the text.
"""
import re
import asyncio
from typing import Optional, Dict, Any, List, Tuple
from concurrent.futures import ThreadPoolExecutor

from core.ai import get_genai_client
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("gemini_table_formatter", "shared")

def extract_markdown_tables(markdown_text: str) -> List[str]:
    """
    Extract all Markdown tables from the provided text.
    """
    # A robust markdown table regex matching standard GFM tables
    # It looks for lines starting with | and containing |.
    pattern = r'(^\|[^\n]+\|\s*\n\|[\s\-:|]+\|\s*\n(?:\|[^\n]+\|\s*\n)*)'
    matches = re.finditer(pattern, markdown_text + "\n", flags=re.MULTILINE)
    return [m.group(0).strip() for m in matches]

def replace_markdown_tables(markdown_text: str, replacements: List[str]) -> str:
    """
    Replace markdown tables in the text with the provided replacements.
    """
    pattern = r'(^\|[^\n]+\|\s*\n\|[\s\-:|]+\|\s*\n(?:\|[^\n]+\|\s*\n)*)'
    parts = re.split(pattern, markdown_text + "\n", flags=re.MULTILINE)
    
    result = []
    replace_idx = 0
    for i, part in enumerate(parts):
        # Even indexes: normal text. Odd indexes: tables.
        if i % 2 == 1:
            if replace_idx < len(replacements):
                result.append("\n\n" + replacements[replace_idx] + "\n\n")
                replace_idx += 1
            else:
                result.append(part)
        else:
            result.append(part)
            
    return "".join(result).strip()

def _build_table_prompt(table_text: str, table_number: int, source_id: Optional[str] = None, source_name: Optional[str] = None, source_type: str = "file") -> str:
    """Build the Gemini prompt for formatting a single Markdown table."""
    source_info = ""
    if source_id and source_name:
        label = "FileUpload ID" if source_type == "file" else "WebScrape ID"
        source_info = f"\nSOURCE CONTEXT: This table is part of {source_type} '{source_name}' ({label}: {source_id})."

    return f"""You are a table analysis and formatting expert. I have extracted a Markdown table from a document.{source_info}

The data includes:
- A Markdown table structure

YOUR TASK:
1. Understand the columns and rows of the supplied Markdown table.
2. If table has nested structure (parent-child relationships):
   - FLATTEN the table so each row is independent
   - Include parent context in each nested row (use parent IDs/names as columns)
   - Make relationships explicit through shared parent identifiers
3. Create structured markdown format with:
   - Title showing table number {table_number} and source information
   - Summary line describing table purpose, key columns, and data type
   - Column list (including parent context columns if nested)
   - Column summaries explaining the meaning of each column in natural language
   - Data rows in natural language key-value format
4. Preserve all cell values exactly

OUTPUT FORMAT (Structured Markdown):

### Table: Table {table_number} ({source_name or 'Unknown'} - {source_id or 'Unknown ID'})
**Summary**: [Brief description of table contents, purpose, key columns, and data type]
**Columns**: [Comma-separated list of column headers]
**Column Summaries**:
- [Column 1]: [Brief natural language explanation of what this column represents and its meaning in the context of this table]
- [Column 2]: [Brief natural language explanation of what this column represents and its meaning in the context of this table]

**Row 1 (first row, 1st entry)**: [Natural language sentence that MUST include the VERBATIM column header name and VERBATIM cell value for every column, e.g., "Year: 1289, Population: 3,000, with an annual percentage change (±% p.a.) of +9.63%"]

**Row 2 (second row, 2nd entry)**: [Natural language sentence that MUST include the VERBATIM column header name and VERBATIM cell value for every column, e.g., "Year: 1348, Population: 7,000, showing a growth rate (±% p.a.) of +12.5%"]

CRITICAL: VERBATIM COLUMN HEADERS AND CELL VALUES IN EVERY ROW
Each row description MUST contain:
1. The EXACT column header name as it appears in the table (verbatim, not paraphrased)
2. The EXACT cell value as it appears in the table (verbatim, not rounded or summarized)
This is essential because RAG search uses keyword matching to find specific rows.
If a user searches for a column name or cell value, it MUST appear verbatim in the row description.

Markdown Table Data:
{table_text}

Return the formatted table in the markdown KV format shown above."""


_GEMINI_TABLE_CONCURRENCY = 5

async def _format_single_table(genai_client, table_text: str, table_number: int,
                                semaphore: asyncio.Semaphore, executor: ThreadPoolExecutor,
                                source_id: Optional[str] = None, source_name: Optional[str] = None, source_type: str = "file") -> Optional[Dict[str, Any]]:
    """Format a single table with Gemini. Returns dict with markdown + metrics, or None on failure."""
    input_chars = len(table_text)
    input_words = len(table_text.split()) if table_text.strip() else 0
    logger.info(f"🤖 [GEMINI_TABLE_{table_number}] Formatting table: {input_chars} chars")

    prompt = _build_table_prompt(table_text, table_number, source_id, source_name, source_type)

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
        
        if source_id or source_name:
            source_footer = f"\n\n*Source: {source_type.capitalize()} ID {source_id} ({source_name or 'N/A'})*"
            result += source_footer

        output_chars = len(result)
        output_words = len(result.split()) if result else 0

        input_tokens = 0
        output_tokens = 0
        try:
            if hasattr(response, 'usage_metadata') and response.usage_metadata:
                um = response.usage_metadata
                input_tokens = getattr(um, 'prompt_token_count', 0) or 0
                output_tokens = getattr(um, 'candidates_token_count', 0) or 0
                logger.info(f"📊 [GEMINI_TABLE_{table_number}] Tokens: input={input_tokens}, output={output_tokens}")
        except Exception as te:
            logger.warning(f"⚠️ [GEMINI_TABLE_{table_number}] Could not extract token usage: {te}")

        logger.info(f"✅ [GEMINI_TABLE_{table_number}] Formatted: {output_chars} chars, {output_words} words")
        return {
            "markdown": result,
            "table_index": table_number,
            "table_character_count_input": input_chars,
            "table_word_count_input": input_words,
            "table_word_count_output": output_words,
            "table_character_count_output": output_chars,
            "table_input_token_count": input_tokens,
            "table_output_token_count": output_tokens,
        }

    except Exception as e:
        logger.error(f"❌ [GEMINI_TABLE_{table_number}] Failed: {e}")
        return None

async def format_tables_with_gemini(tables: List[str],
                                    source_id: Optional[str] = None, source_name: Optional[str] = None, source_type: str = "file") -> Dict[str, Any]:
    logger.info("=" * 80)
    logger.info("🤖 [GEMINI_TABLES] === START TABLE FORMATTING WITH GEMINI ===")
    logger.info("=" * 80)

    if not tables:
        return {"tables_markdown": [], "tables_metadata": []}

    try:
        genai_client = get_genai_client()
        if not genai_client:
            logger.error("❌ [GEMINI_TABLES] Gemini client not available")
            return {"tables_markdown": [], "tables_metadata": [], "error": "Gemini client not configured"}

        semaphore = asyncio.Semaphore(_GEMINI_TABLE_CONCURRENCY)
        executor = ThreadPoolExecutor(max_workers=_GEMINI_TABLE_CONCURRENCY)

        tasks = [
            _format_single_table(genai_client, table, idx + 1, semaphore, executor, source_id, source_name, source_type)
            for idx, table in enumerate(tables)
        ]
        results = await asyncio.gather(*tasks)

        all_markdown = []
        tables_metadata = []
        success_count = 0
        
        for idx, result in enumerate(results):
            if result:
                all_markdown.append(result["markdown"])
                tables_metadata.append({k: v for k, v in result.items() if k != "markdown"})
                success_count += 1
            else:
                # If a table fails, keep original to maintain index sync for replacements
                logger.warning(f"⚠️ [GEMINI_TABLES] Failed to format, keeping original table {idx}")
                all_markdown.append(tables[idx])

        logger.info(f"📊 [GEMINI_TABLES] Results: {success_count} succeeded out of {len(tables)}")

        return {
            "tables_markdown": all_markdown,
            "tables_metadata": tables_metadata,
            "format": "markdown_kv"
        }

    except Exception as e:
        logger.error(f"❌ [GEMINI_TABLES] Unexpected error: {e}")
        return {"tables_markdown": [], "tables_metadata": [], "error": str(e)}

async def process_extracted_markdown(
    markdown_content: str, 
    source_id: Optional[str] = None, 
    source_name: Optional[str] = None, 
    source_type: str = "file"
) -> Tuple[str, List[Dict[str, Any]]]:
    """
    Unified function for processing Kreuzberg Markdown format.
    1. Extracts Markdown tables
    2. Sends tables to Gemini for intelligent formatting
    3. Replaces original tables in the markdown with the formatted ones
    """
    logger.info("=" * 80)
    logger.info("[MD_PROCESS] === UNIFIED MARKDOWN PROCESSING ===")
    logger.info("=" * 80)

    # 1. Extract Markdown tables
    logger.info("[MD_PROCESS] Step 1: Extracting markdown tables...")
    tables = extract_markdown_tables(markdown_content)
    logger.info(f"[MD_PROCESS] Found {len(tables)} tables")

    if not tables:
        logger.info("[MD_PROCESS] No tables to process. Returning original markdown.")
        return markdown_content, []

    # 2. Format tables with Gemini
    logger.info("[MD_PROCESS] Step 2: Formatting tables with Gemini...")
    formatted_results = await format_tables_with_gemini(tables, source_id=source_id, source_name=source_name, source_type=source_type)
    
    formatted_tables = formatted_results.get("tables_markdown", [])
    tables_metadata = formatted_results.get("tables_metadata", [])

    # 3. Final Content
    logger.info("[MD_PROCESS] Step 3: Replacing tables in markdown...")
    if formatted_tables and len(formatted_tables) == len(tables):
        merged_content = replace_markdown_tables(markdown_content, formatted_tables)
    else:
        logger.warning("[MD_PROCESS] Table replacement mismatch or error... skipping replacing")
        merged_content = markdown_content
        
    logger.info(f"[MD_PROCESS] Merged content size: {len(merged_content)} chars")
    return merged_content, tables_metadata
