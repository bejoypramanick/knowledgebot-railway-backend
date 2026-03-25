"""
Kreuzberg Document Intelligence Integration
Replaces docling-serve with a fast, synchronous REST API call to the Kreuzberg container.
"""
import asyncio
import time
import httpx
import os
from typing import Tuple, Dict, Any, Optional, List
import json
import re
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("kreuzberg_integration", "shared")

KREUZBERG_API_URL = os.environ.get("KREUZBERG_API_URL", "http://localhost:8000")
KREUZBERG_API_TIMEOUT = float(os.environ.get("KREUZBERG_API_TIMEOUT", "300.0"))

def retry_on_connection_error(max_retries: int = 3, delay: float = 1.0):
    """Decorator to retry a function on httpx connection errors."""
    def decorator(func):
        import functools
        @functools.wraps(func)
        async def wrapper(*args, **kwargs):
            last_err = None
            for i in range(max_retries):
                try:
                    return await func(*args, **kwargs)
                except (httpx.ConnectError, httpx.ConnectTimeout, httpx.RemoteProtocolError, httpx.ReadTimeout, httpx.ReadError, Exception) as e:
                    # We catch Exception more broadly if it looks like a network error, 
                    # but specifically target httpcore and httpx types
                    if not any(isinstance(e, t) for t in (httpx.NetworkError, httpx.TimeoutException)):
                        # If it's not a known httpx error, check if it's httpcore
                        if "httpcore" not in str(type(e)):
                            raise e
                    
                    last_err = e
                    # Log more details about the error
                    error_detail = f"{type(e).__name__}: {str(e)}"
                    wait = delay * (2 ** i) # Exponential backoff
                    logger.warning(f"⚠️ [KREUZBERG_RETRY] {error_detail} on attempt {i+1}/{max_retries}. Target: {KREUZBERG_API_URL}. Retrying in {wait}s...")
                    await asyncio.sleep(wait)
            
            logger.error(f"❌ [KREUZBERG_RETRY_FAILED] Max retries reached for {func.__name__}. Last error: {type(last_err).__name__}: {str(last_err)}")
            if "localhost" in str(KREUZBERG_API_URL):
                logger.warning("💡 [KREUZBERG_TIP] You are connecting to localhost:8000. If running in containers (e.g. Railway), ensure KREUZBERG_API_URL is set to the service's internal domain.")
            raise last_err
        return wrapper
    return decorator

async def download_file_from_s3(presigned_url: str) -> bytes:
    """Download file from S3 using presigned URL to memory."""
    logger.info(f"[KREUZBERG] Downloading file from S3 to memory...")
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(presigned_url)
        response.raise_for_status()
        logger.info(f"[KREUZBERG] Downloaded {len(response.content)} bytes from S3.")
        return response.content

def table_to_kv_markdown(
    cells: List[List[str]], 
    table_index: int, 
    page_number: Optional[int] = None,
    source_name: Optional[str] = None,
    source_id: Optional[str] = None
) -> str:
    """
    Convert a 2D list of cells into a Markdown KV format.
    Ensures each row is a single line to prevent Gemini FileSearch chunking issues.
    """
    if not cells or len(cells) < 1:
        return ""
    
    headers = cells[0]
    rows = cells[1:] if len(cells) > 1 else []
    
    page_info = f" (Page {page_number})" if page_number else ""
    context_info = f" - {source_name}" if source_name else ""
    id_info = f" ({source_id})" if source_id else ""
    
    lines = [f"### Table {table_index}{page_info}{context_info}{id_info}"]
    
    # Simple summary if possible
    lines.append(f"**Summary**: Structured data table with {len(rows)} rows and {len(headers)} columns.")
    lines.append(f"**Columns**: {', '.join(headers)}")
    lines.append("")

    for i, row in enumerate(rows):
        kv_pairs = []
        for j, cell in enumerate(row):
            header = headers[j] if j < len(headers) else f"Column {j+1}"
            # Clean cell value and header of newlines/excess whitespace
            clean_header = str(header).replace("\n", " ").strip()
            clean_cell = str(cell).replace("\n", " ").strip()
            kv_pairs.append(f"{clean_header}: {clean_cell}")
        
        # Prepend table index and page info to every row for RAG retrieval stability
        row_prefix = f"**Table {table_index}{page_info} Row {i+1}**"
        row_line = f"{row_prefix}: {', '.join(kv_pairs)}"
        lines.append(row_line)
    
    return "\n".join(lines)

@retry_on_connection_error(max_retries=5, delay=2.0)
async def process_with_kreuzberg(
    presigned_url: str,
    original_filename: str,
    mime_type: str,
    worker_type: str = "file",
    source_id: Optional[str] = None,
    source_name: Optional[str] = None
) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Send a document to Kreuzberg for extraction.
    Returns (markdown_content, metadata_dict).
    """
    start_time = time.time()
    
    # Sanitize URL to prevent double slashes
    base_url = str(KREUZBERG_API_URL).strip("/")
    endpoint = f"{base_url}/extract"

    logger.info(f"================================================================================")
    logger.info(f"[KREUZBERG] === KREUZBERG DOCUMENT EXTRACTION ===")
    logger.info(f"[KREUZBERG] File: {original_filename}")
    logger.info(f"[KREUZBERG] MIME Type: {mime_type}")
    logger.info(f"[KREUZBERG] API URL: {endpoint}")
    
    # DNS Diagnostics
    try:
        import socket
        hostname = endpoint.split("//")[-1].split(":")[0].split("/")[0]
        ip_addr = socket.gethostbyname(hostname)
        logger.info(f"[KREUZBERG_DNS] Resolved {hostname} to {ip_addr}")
    except Exception as dns_err:
        logger.warning(f"⚠️ [KREUZBERG_DNS] Could not resolve hostname {hostname}: {dns_err}")
        
    logger.info("=" * 80)

    try:
        # 1. Download file from S3 into memory
        file_bytes = await download_file_from_s3(presigned_url)

        # 2. Prepare Kreuzberg API Request
        logger.info(f"[KREUZBERG] Sending extraction request into {endpoint}...")
        
        async with httpx.AsyncClient(timeout=KREUZBERG_API_TIMEOUT) as client:
            # We use 'files' (plural) as per previous working commits
            files_payload = [
                ('file', (original_filename, file_bytes, mime_type))
            ]
            
            data = {
                'output_format': 'markdown'
            }
            
            response = await client.post(endpoint, files=files_payload, data=data)
            
            if response.status_code != 200:
                logger.error(f"[KREUZBERG] API returned error {response.status_code}: {response.text}")
                return None, {"error": f"API Error {response.status_code}: {response.text}"}
                
            result = response.json()
            
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        # 3. Parse and normalize response
        # Kreuzberg returns an object with 'content' (markdown) and 'tables' (structured data)
        # Based on GitHub schema: ExtractionResult { content, tables, metadata }
        if isinstance(result, list) and len(result) > 0:
            result = result[0]
            
        markdown_content = result.get("content", "")
        if not markdown_content and "text" in result:
            markdown_content = result.get("text", "")
            
        tables = result.get("tables", [])
        response_metadata = result.get("metadata", {})
        
        # 4. Process tables into KV format and replace in markdown
        if tables:
            logger.info(f"[KREUZBERG] Processing {len(tables)} tables into KV format...")
            for i, table_data in enumerate(tables):
                cells = table_data.get("cells", [])
                original_markdown = table_data.get("markdown", "")
                page_num = table_data.get("page_number")
                
                if cells:
                    kv_markdown = table_to_kv_markdown(
                        cells, 
                        i + 1, 
                        page_num, 
                        source_name=source_name or original_filename,
                        source_id=source_id
                    )
                    if original_markdown and original_markdown in markdown_content:
                        # Add some padding or clear markers
                        # Using replacement for exact match of the markdown representation Kreuzberg provided
                        markdown_content = markdown_content.replace(original_markdown, f"\n\n{kv_markdown}\n\n")
                    else:
                        # Fallback: if we can't find the exact markdown, append at the end or log warning
                        logger.warning(f"[KREUZBERG] Could not find exact location for table {i+1} in content.")
                        markdown_content += f"\n\n{kv_markdown}\n\n"

        metadata = {
            "processing_time_ms": processing_time_ms,
            "images_extracted": 0,
            "images_with_ocr": 0,
            "content_format": "markdown_kv",
            "kreuzberg_metadata": response_metadata,
            "tables_processed": len(tables)
        }

        logger.info(f"✅ [KREUZBERG] Extraction successful in {processing_time_ms}ms")
        logger.info(f"✅ [KREUZBERG] Extracted {len(markdown_content)} characters")
        
        return markdown_content, metadata

    except Exception as e:
        logger.error(f"❌ [KREUZBERG] Unexpected error during extraction: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return None, {"error": str(e)}

async def should_use_kreuzberg_for_file(filename: str, mime_type: str, file_size: int = 0) -> bool:
    """Determine if a file should be sent to Kreuzberg."""
    # Kreuzberg handles many formats. As a safe bet, we route typical documents.
    supported_extensions = {
        '.pdf', '.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.xls', 
        '.html', '.htm', '.rtf', '.epub', '.csv'
    }
    
    ext = os.path.splitext(filename.lower())[1]
    if ext in supported_extensions:
        return True
        
    supported_mimes = [
        'application/pdf',
        'application/vnd.openxmlformats-officedocument',
        'application/msword',
        'text/html'
    ]
    
    if any(mime_type.startswith(m) for m in supported_mimes):
        return True
        
    return False

def create_markdown_temp_file(content: str) -> str:
    import tempfile
    fd, path = tempfile.mkstemp(suffix='.md')
    with os.fdopen(fd, 'w', encoding='utf-8') as f:
        f.write(content)
    return path
