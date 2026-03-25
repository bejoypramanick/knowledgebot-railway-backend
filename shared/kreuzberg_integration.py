"""
Kreuzberg Document Intelligence Integration
Provides a fast, synchronous REST API call to the Kreuzberg container.
"""
import time
import httpx
import os
from typing import Tuple, Dict, Any, Optional
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("kreuzberg_integration", "shared")

KREUZBERG_API_URL = os.environ.get("KREUZBERG_API_URL", "http://kreuzberg:8000")
KREUZBERG_API_TIMEOUT = float(os.environ.get("KREUZBERG_API_TIMEOUT", "300.0"))

async def download_file_from_s3(presigned_url: str) -> bytes:
    """Download file from S3 using presigned URL to memory."""
    logger.info(f"[KREUZBERG] Downloading file from S3 to memory...")
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(presigned_url)
        response.raise_for_status()
        logger.info(f"[KREUZBERG] Downloaded {len(response.content)} bytes from S3.")
        if response.status_code == 200:
            return response.content
        return b""


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
    base_url = str(KREUZBERG_API_URL).strip("/")
    endpoint = f"{base_url}/extract"

    logger.info(f"[KREUZBERG] Extracting {original_filename} from {endpoint}")

    try:
        file_bytes = await download_file_from_s3(presigned_url)

        async with httpx.AsyncClient(timeout=KREUZBERG_API_TIMEOUT) as client:
            response = await client.post(
                endpoint,
                files=[('files', (original_filename, file_bytes, mime_type))],
                data={"output_format": "markdown"}
            )

        if response.status_code != 200:
            logger.error(f"[KREUZBERG] API error {response.status_code}: {response.text}")
            return None, {"error": f"API Error {response.status_code}: {response.text}"}

        processing_time_ms = int((time.time() - start_time) * 1000)
        markdown_content = response.text
        logger.info(f"✅ [KREUZBERG] Done in {processing_time_ms}ms — {len(markdown_content)} characters")

        return markdown_content, {"processing_time_ms": processing_time_ms, "content_format": "markdown"}

    except Exception as e:
        logger.error(f"❌ [KREUZBERG] Extraction failed: {e}")
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
