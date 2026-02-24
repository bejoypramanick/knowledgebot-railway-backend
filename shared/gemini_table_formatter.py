"""
Use Gemini API to convert docling tables into meaningful JSON format.
Tables are extracted, sent to Gemini for intelligent formatting,
then merged back with non-table content.
"""
import json
from typing import Optional, Dict, Any, List

from core.ai import get_genai_client
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("gemini_table_formatter", "docling")


def extract_tables_from_docling_json(json_content: str) -> List[Dict[str, Any]]:
    """
    Extract all tables from docling JSON output.

    Args:
        json_content: Raw JSON string from docling

    Returns:
        List of table objects with metadata
    """
    try:
        doc = json.loads(json_content)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse docling JSON for table extraction")
        return []

    tables = doc.get("tables", [])
    logger.info(f"📊 Extracted {len(tables)} tables from docling JSON")

    return tables


def extract_non_table_content_from_docling(json_content: str) -> str:
    """
    Extract all non-table content (texts, groups) from docling JSON as markdown.

    Args:
        json_content: Raw JSON string from docling

    Returns:
        Markdown string with non-table content
    """
    try:
        doc = json.loads(json_content)
    except (json.JSONDecodeError, TypeError):
        logger.warning("Failed to parse docling JSON for text extraction")
        return ""

    from shared.docling_content_converter import convert_docling_to_markdown

    # Convert to markdown (this includes tables, we'll filter them out later)
    markdown_content = convert_docling_to_markdown(json_content)

    # Remove table sections from markdown (they start with ### Table)
    lines = markdown_content.split('\n')
    result_lines = []
    skip_table = False

    for line in lines:
        if line.startswith('### Table'):
            skip_table = True
            continue
        if skip_table:
            if line.startswith('```'):
                skip_table = False
            continue
        result_lines.append(line)

    # Clean up excess blank lines
    content = '\n'.join(result_lines)
    while '\n\n\n' in content:
        content = content.replace('\n\n\n', '\n\n')

    return content.strip()


async def format_tables_with_gemini(tables: List[Dict[str, Any]]) -> Dict[str, Any]:
    """
    Send tables to Gemini model to convert into meaningful JSON format.

    Args:
        tables: List of table objects from docling

    Returns:
        Dictionary with formatted tables as JSON
    """
    if not tables:
        logger.info("No tables to format")
        return {"tables": {}}

    try:
        genai_client = get_genai_client()
        if not genai_client:
            logger.error("❌ Gemini client not available")
            return {"tables": {}, "error": "Gemini client not configured"}

        # Prepare table data for Gemini
        tables_text = json.dumps(tables, indent=2, ensure_ascii=False)

        logger.info(f"🤖 Sending {len(tables)} tables to Gemini for formatting...")
        logger.debug(f"Tables data size: {len(tables_text)} chars")

        # Create prompt for Gemini to format tables
        prompt = f"""You are a data formatting expert. I have extracted tables from a PDF document using docling.

Please analyze these tables and convert them into a meaningful JSON structure that is:
1. Easy to understand and search
2. Preserves all data relationships
3. Uses descriptive keys and structures
4. Groups related data logically

For each table:
- Identify the row/column headers
- Create a consistent JSON structure
- Use the first column as a key if it's unique (like ID, number, name)
- Preserve all cell values exactly

Return ONLY valid JSON with a "tables" key containing your formatted result.
Do not include explanations, only the JSON output.

Docling tables data:
{tables_text}

Return the formatted tables as valid JSON."""

        # Call Gemini API
        response = genai_client.models.generate_content(
            model="gemini-1.5-flash",
            contents=prompt
        )

        if not response or not response.text:
            logger.error("❌ Empty response from Gemini")
            return {"tables": {}, "error": "Empty Gemini response"}

        logger.info(f"✅ Gemini formatted tables (response length: {len(response.text)} chars)")

        # Parse the JSON response
        try:
            # Try to extract JSON from the response
            response_text = response.text.strip()

            # If wrapped in markdown code block, extract it
            if response_text.startswith("```"):
                json_start = response_text.find('{')
                json_end = response_text.rfind('}') + 1
                if json_start >= 0 and json_end > json_start:
                    response_text = response_text[json_start:json_end]

            formatted = json.loads(response_text)
            logger.info(f"📋 Successfully parsed Gemini formatted tables")
            return formatted

        except json.JSONDecodeError as e:
            logger.error(f"❌ Failed to parse Gemini response as JSON: {e}")
            logger.debug(f"Response text: {response.text[:500]}")
            return {"tables": {}, "error": f"Invalid JSON response: {str(e)}"}

    except Exception as e:
        logger.error(f"❌ Error formatting tables with Gemini: {e}")
        return {"tables": {}, "error": str(e)}


def merge_content_with_formatted_tables(
    text_content: str,
    formatted_tables: Dict[str, Any]
) -> str:
    """
    Merge non-table text content with formatted tables into a single markdown document.

    Args:
        text_content: Markdown text without tables
        formatted_tables: Dictionary with formatted tables from Gemini

    Returns:
        Merged markdown content
    """
    # Add formatted tables section
    tables_section = ""

    if formatted_tables and "tables" in formatted_tables:
        tables_data = formatted_tables["tables"]
        if tables_data:
            tables_section = "\n\n## Formatted Tables\n\n```json\n"
            tables_section += json.dumps(tables_data, indent=2, ensure_ascii=False)
            tables_section += "\n```"

    # Combine text and tables
    merged = text_content
    if tables_section:
        merged += tables_section

    logger.info(f"📝 Merged content: {len(merged)} chars (text: {len(text_content)}, tables: {len(tables_section)})")

    return merged
