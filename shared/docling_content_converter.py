"""
Convert Docling JSON (DoclingDocument v2) to clean Markdown for LLM consumption.

Strips all docling noise (bounding boxes, provenance, self_refs, origins, etc.)
and extracts only the meaningful content:
- texts → markdown headings, paragraphs, list items (just the text + label)
- tables → simple JSON array of row objects keyed by column headers (just cell values)
- groups → recursive children
"""
import json
import logging

logger = logging.getLogger("docling_content_converter")


def convert_docling_to_markdown(json_content: str) -> str:
    """
    Convert docling JSON output to a markdown document.

    Preserves reading order. Strips all docling metadata (bounding boxes,
    provenance, refs) and outputs only text content + clean table JSON.

    Args:
        json_content: Raw JSON string from docling conversion

    Returns:
        Markdown string with text content and structured tables
    """
    try:
        doc = json.loads(json_content)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Failed to parse docling JSON, returning raw content: {e}")
        return json_content

    texts = doc.get("texts", [])
    tables = doc.get("tables", [])
    groups = doc.get("groups", [])
    body = doc.get("body", {})
    children = body.get("children", [])

    if not children:
        # No body.children — fall back to extracting text values directly
        # from top-level arrays (still strips all bounding box / provenance noise)
        logger.warning("No body.children found, extracting from top-level texts/tables arrays")
        return _fallback_extract(texts, tables)

    parts = []
    for child in children:
        _render_child(child, texts, tables, groups, parts)

    return "\n\n".join(parts)


def _fallback_extract(texts: list, tables: list) -> str:
    """
    Fallback when body.children is missing: extract just text values
    and table cell values from top-level arrays (no reading order, but
    still strips all bounding box / provenance / ref noise).
    """
    parts = []
    for item in texts:
        md = _render_text(item)
        if md:
            parts.append(md)
    for item in tables:
        md = _render_table(item)
        if md:
            parts.append(md)
    return "\n\n".join(parts) if parts else ""


def _resolve_ref(ref: str):
    """Parse a $ref like '#/texts/5' into (collection_name, index)."""
    if not ref or not ref.startswith("#/"):
        return None, None
    segments = ref.lstrip("#/").split("/")
    if len(segments) != 2:
        return None, None
    collection = segments[0]
    try:
        idx = int(segments[1])
    except (ValueError, IndexError):
        return None, None
    return collection, idx


def _render_child(child, texts, tables, groups, parts):
    """Render a single body child item to markdown, appending to parts."""
    ref = child.get("$ref")
    if not ref:
        return

    collection, idx = _resolve_ref(ref)
    if collection is None:
        return

    if collection == "texts" and 0 <= idx < len(texts):
        md = _render_text(texts[idx])
        if md:
            parts.append(md)

    elif collection == "tables" and 0 <= idx < len(tables):
        md = _render_table(tables[idx])
        if md:
            parts.append(md)

    elif collection == "groups" and 0 <= idx < len(groups):
        group = groups[idx]
        for group_child in group.get("children", []):
            _render_child(group_child, texts, tables, groups, parts)


def _render_text(item: dict) -> str:
    """Convert a text item to markdown based on its label."""
    text = item.get("text", "").strip()
    if not text:
        return ""

    label = item.get("label", "text")

    if label == "title":
        return f"# {text}"

    if label == "section_header":
        level = item.get("level", 2)
        level = max(1, min(level, 6))
        return f"{'#' * level} {text}"

    if label == "list_item":
        marker = item.get("marker", "-")
        enumerated = item.get("enumerated", False)
        if enumerated and marker:
            return f"{marker} {text}"
        return f"- {text}"

    if label == "caption":
        return f"*{text}*"

    # Default: plain paragraph
    return text


def _render_table(table: dict) -> str:
    """
    Convert a table item to a clean, simple JSON that an LLM can easily understand.

    Extracts cell values from data.table_cells, reconstructs the grid,
    and outputs a flat JSON array of row objects keyed by column headers.
    """
    data = table.get("data", {})
    table_cells = data.get("table_cells", [])
    num_rows = data.get("num_rows", 0)
    num_cols = data.get("num_cols", 0)

    if not table_cells or num_rows == 0 or num_cols == 0:
        text = table.get("text", "")
        if text:
            return f"```\n{text}\n```"
        return ""

    # Build 2D grid from cell values
    grid = [["" for _ in range(num_cols)] for _ in range(num_rows)]
    for cell in table_cells:
        row = cell.get("start_row_offset_idx", 0)
        col = cell.get("start_col_offset_idx", 0)
        cell_text = cell.get("text", "")
        if 0 <= row < num_rows and 0 <= col < num_cols:
            grid[row][col] = cell_text

    # Determine page provenance
    prov = table.get("prov", [])
    page_str = ""
    if prov:
        page_no = prov[0].get("page_no", prov[0].get("page", ""))
        if page_no:
            page_str = f" (Page {page_no})"

    # Use first row as headers; fall back to Col1, Col2, ... if empty
    header_row = grid[0] if grid else []
    headers = [h.strip() for h in header_row]
    if not any(headers):
        headers = [f"Col{i+1}" for i in range(num_cols)]

    # Build simple row dicts: {"Header": "value", ...}
    json_rows = []
    for row in grid[1:]:
        row_dict = {}
        for i, val in enumerate(row):
            key = headers[i] if i < len(headers) else f"Col{i+1}"
            row_dict[key] = val
        json_rows.append(row_dict)

    json_block = json.dumps(json_rows, indent=2, ensure_ascii=False)

    return f"### Table{page_str}\n\n```json\n{json_block}\n```"
