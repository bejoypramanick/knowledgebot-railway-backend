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
from shared.otel_logger import get_otel_logger
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("docling_content_converter", "shared")


def convert_docling_to_markdown(json_content: str, include_tables: bool = True) -> str:
    """
    Convert docling JSON output to a markdown document.

    Preserves reading order. Strips all docling metadata (bounding boxes,
    provenance, refs) and outputs only text content + clean table JSON.

    Args:
        json_content: Raw JSON string from docling conversion
        include_tables: Whether to include tables in output (default True)

    Returns:
        Markdown string with text content and structured tables (if include_tables=True)
    """
    try:
        doc = json.loads(json_content)
    except (json.JSONDecodeError, TypeError) as e:
        logger.warning(f"Failed to parse docling JSON, returning raw content: {e}")
        return json_content

    texts = doc.get("texts", [])
    tables = doc.get("tables", []) if include_tables else []
    groups = doc.get("groups", [])
    body = doc.get("body", {})
    children = body.get("children", [])

    logger.info(f"📊 [DOCLING_STRUCTURE] Total texts: {len(texts)}, tables: {len(tables)}, groups: {len(groups)}")
    logger.info(f"📊 [DOCLING_STRUCTURE] Body children: {len(children)}")

    # Log text labels distribution for debugging
    if texts:
        label_counts = {}
        for text in texts:
            label = text.get("label", "text")
            label_counts[label] = label_counts.get(label, 0) + 1
        logger.info(f"📊 [TEXT_LABELS] Distribution: {label_counts}")

    if not children:
        # No body.children — fall back to extracting text values directly
        # from top-level arrays (still strips all bounding box / provenance noise)
        logger.warning(f"⚠️ [FALLBACK] No body.children found, using fallback extraction from {len(texts)} texts and {len(tables)} tables")
        return _fallback_extract(texts, tables)

    logger.info(f"✅ [STRUCTURE] Using body.children with {len(children)} children")
    
    # Track which text indices are rendered from body.children
    rendered_text_indices = set()
    parts = []
    for child in children:
        _render_child(child, texts, tables, groups, parts, rendered_text_indices)

    logger.info(f"📝 [OUTPUT] Generated {len(parts)} content blocks from structure")
    
    # INVESTIGATE: Show which text items were skipped
    total_text_items = len(texts)
    skipped_count = total_text_items - len(rendered_text_indices)
    if skipped_count > 0:
        logger.warning(f"⚠️  [INVESTIGATION] {skipped_count} out of {total_text_items} text items NOT in body.children")
        logger.warning(f"⚠️  [INVESTIGATION] Rendered indices count: {len(rendered_text_indices)}")
        
        # Find skipped indices
        skipped_indices = [i for i in range(total_text_items) if i not in rendered_text_indices]
        logger.warning(f"⚠️  [INVESTIGATION] First 30 skipped indices: {skipped_indices[:30]}")
        
        # Show samples of skipped items to check if they contain article content
        logger.warning(f"⚠️  [INVESTIGATION] === SAMPLE SKIPPED TEXT ITEMS ===")
        for idx in skipped_indices[:10]:
            if idx < len(texts):
                skipped_text = texts[idx].get("text", "")[:200]
                skipped_label = texts[idx].get("label", "unknown")
                logger.warning(f"⚠️  [INVESTIGATION] Index {idx} ({skipped_label}): {repr(skipped_text)}")
        logger.warning(f"⚠️  [INVESTIGATION] === END SAMPLE ===")
    
    return "\n\n".join(parts)


def _fallback_extract(texts: list, tables: list) -> str:
    """
    Fallback when body.children is missing: extract just text values
    and table cell values from top-level arrays (no reading order, but
    still strips all bounding box / provenance / ref noise).
    """
    parts = []
    text_count = 0
    skipped_texts = 0

    for item in texts:
        md = _render_text(item)
        if md:
            parts.append(md)
            text_count += 1
        else:
            skipped_texts += 1

    for item in tables:
        md = _render_table(item)
        if md:
            parts.append(md)

    logger.info(f"📝 [FALLBACK_EXTRACT] Extracted {text_count} texts, skipped {skipped_texts} empty texts, added {len([p for p in parts if p.startswith('```json')])} tables")
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


def _render_child(child, texts, tables, groups, parts, rendered_text_indices=None):
    """Render a single body child item to markdown, appending to parts."""
    ref = child.get("$ref")
    if not ref:
        return

    collection, idx = _resolve_ref(ref)
    if collection is None:
        return

    if collection == "texts" and 0 <= idx < len(texts):
        if rendered_text_indices is not None:
            rendered_text_indices.add(idx)
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
            _render_child(group_child, texts, tables, groups, parts, rendered_text_indices)


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

    # Handle page breaks and structural elements
    if label in ["page_break", "footnote_ref", "page_footer", "page_header"]:
        return ""  # Skip structural elements

    # Default: plain paragraph or text
    # Includes labels like "text", "paragraph", "paragraph_continuation", etc.
    return text


def _render_table(table: dict) -> str:
    """
    Convert a docling table to clean JSON using all cell metadata.

    Uses col_header/row_header flags and cell spans from docling to
    reconstruct the table exactly as it appears in the PDF, then outputs
    a simple JSON that an LLM can understand.
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

    # Build 2D grid
    grid = [["" for _ in range(num_cols)] for _ in range(num_rows)]
    # Track col_header and row_header per cell position
    is_col_header = [[False] * num_cols for _ in range(num_rows)]
    is_row_header = [[False] * num_cols for _ in range(num_rows)]
    # Track which cells actually belong to which starting row (for spanning cells)
    cell_start_rows = [[None for _ in range(num_cols)] for _ in range(num_rows)]

    for cell in table_cells:
        text = cell.get("text", "")
        r_start = cell.get("start_row_offset_idx", 0)
        c_start = cell.get("start_col_offset_idx", 0)
        r_end = cell.get("end_row_offset_idx", r_start + 1)
        c_end = cell.get("end_col_offset_idx", c_start + 1)
        ch = cell.get("col_header", False)
        rh = cell.get("row_header", False)

        # Only fill starting position with actual text (avoid duplication in spanning cells)
        # Other spanned positions get filled with empty or marker
        if r_start < num_rows and c_start < num_cols:
            grid[r_start][c_start] = text
            is_col_header[r_start][c_start] = ch
            is_row_header[r_start][c_start] = rh
            cell_start_rows[r_start][c_start] = r_start

        # Mark spanned positions so we know they're covered but don't duplicate the text
        for r in range(r_start, min(r_end, num_rows)):
            for c in range(c_start, min(c_end, num_cols)):
                if r != r_start or c != c_start:  # Not the starting cell
                    # Mark that this cell is covered by a spanning cell
                    if grid[r][c] == "":  # Only if not already filled
                        grid[r][c] = ""  # Keep empty, don't duplicate
                        if cell_start_rows[r][c] is None:
                            cell_start_rows[r][c] = r_start  # Track where it came from
                    is_col_header[r][c] = is_col_header[r][c] or ch
                    is_row_header[r][c] = is_row_header[r][c] or rh

    # Identify header rows: rows where ALL cells are col_header
    header_row_indices = []
    for r in range(num_rows):
        if all(is_col_header[r][c] for c in range(num_cols)):
            header_row_indices.append(r)

    # Identify row_header columns: columns where ALL data cells are row_header
    first_data_row = (max(header_row_indices) + 1) if header_row_indices else 0
    row_header_cols = set()
    if first_data_row < num_rows:
        for c in range(num_cols):
            if all(is_row_header[r][c] for r in range(first_data_row, num_rows)):
                row_header_cols.add(c)

    # Build column names from header rows
    if header_row_indices:
        # For multi-row headers, join vertically (e.g. "Revenue" + "Q1" -> "Revenue - Q1")
        col_names = []
        for c in range(num_cols):
            parts = []
            for r in header_row_indices:
                val = grid[r][c].strip()
                if val and val not in parts:
                    parts.append(val)
            col_names.append(" - ".join(parts) if parts else "")
    else:
        col_names = []

    # Make column names unique and non-empty
    headers = _make_unique_headers(col_names, num_cols)

    # Build data rows as dicts
    json_rows = []
    for r in range(first_data_row, num_rows):
        row_dict = {}
        for c in range(num_cols):
            row_dict[headers[c]] = grid[r][c]
        # Skip completely empty rows
        if any(v.strip() for v in row_dict.values()):
            json_rows.append(row_dict)

    # Page provenance
    prov = table.get("prov", [])
    page_str = ""
    if prov:
        page_no = prov[0].get("page_no", prov[0].get("page", ""))
        if page_no:
            page_str = f" (Page {page_no})"

    json_block = json.dumps(json_rows, indent=2, ensure_ascii=False)
    return f"### Table{page_str}\n\n```json\n{json_block}\n```"


def _make_unique_headers(raw_headers: list, num_cols: int) -> list:
    """
    Ensure every column has a unique, non-empty header.
    Empty headers become Col1, Col2, etc.
    Duplicate headers get a numeric suffix: Name, Name_2, Name_3, ...
    """
    if not raw_headers or not any(raw_headers):
        return [f"Col{i+1}" for i in range(num_cols)]

    headers = []
    seen = {}
    for i in range(num_cols):
        h = raw_headers[i] if i < len(raw_headers) else ""
        if not h:
            h = f"Col{i+1}"
        if h in seen:
            seen[h] += 1
            h = f"{h}_{seen[h]}"
        else:
            seen[h] = 1
        headers.append(h)
    return headers
