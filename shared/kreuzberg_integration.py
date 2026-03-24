"""
Kreuzberg Document Intelligence Integration
Replaces docling-serve with a fast, synchronous REST API call to the Kreuzberg container.
"""
import asyncio
import time
import httpx
import os
from typing import Tuple, Dict, Any, Optional
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("kreuzberg_integration", "shared")

KREUZBERG_API_URL = os.environ.get("KREUZBERG_API_URL", "http://localhost:8000")

async def download_file_from_s3(presigned_url: str) -> bytes:
    """Download file from S3 using presigned URL to memory."""
    logger.info(f"[KREUZBERG] Downloading file from S3 to memory...")
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.get(presigned_url)
        response.raise_for_status()
        logger.info(f"[KREUZBERG] Downloaded {len(response.content)} bytes from S3.")
        return response.content

async def process_with_kreuzberg(
    presigned_url: str,
    original_filename: str,
    mime_type: str,
    worker_type: str = "file"
) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Process a document synchronously using Kreuzberg REST API.
    
    Args:
        presigned_url: S3 presigned URL to download the file from.
        original_filename: The original filename.
        mime_type: The detected MIME type of the file.
        worker_type: Worker type ('file' or 'web').
        
    Returns:
        Tuple of (markdown_content, metadata)
    """
    start_time = time.time()
    logger.info("=" * 80)
    logger.info(f"[KREUZBERG] === KREUZBERG DOCUMENT EXTRACTION ===")
    logger.info(f"[KREUZBERG] File: {original_filename}")
    logger.info(f"[KREUZBERG] MIME Type: {mime_type}")
    logger.info(f"[KREUZBERG] API URL: {KREUZBERG_API_URL}")
    logger.info("=" * 80)

    try:
        # 1. Download file from S3 into memory
        file_bytes = await download_file_from_s3(presigned_url)

        # 2. Prepare Kreuzberg API Request
        logger.info(f"[KREUZBERG] Sending extraction request to Kreuzberg API...")
        
        # We assume the endpoint is POST /extract
        endpoint = f"{KREUZBERG_API_URL}/extract"
        
        # Kreuzberg typically returns markdown by default when requested or configurable via query params/form.
        # We will try to pass standard parameters.
        files = {
            'file': (original_filename, file_bytes, mime_type)
        }
        
        data = {
            'output_format': 'markdown'
        }

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(endpoint, files=files, data=data)
            
            if response.status_code != 200:
                logger.error(f"[KREUZBERG] API returned error {response.status_code}: {response.text}")
                return None, {"error": f"API Error {response.status_code}: {response.text}"}
                
            result = response.json()
            
        processing_time_ms = int((time.time() - start_time) * 1000)
        
        # 3. Parse and normalize response
        # Kreuzberg might return a list if it processes multiple files, or an object.
        if isinstance(result, list) and len(result) > 0:
            result = result[0]
            
        markdown_content = result.get("content", "")
        if not markdown_content and "text" in result:
            markdown_content = result.get("text", "")
            
        response_metadata = result.get("metadata", {})
        
        metadata = {
            "processing_time_ms": processing_time_ms,
            "images_extracted": 0,
            "images_with_ocr": 0,
            "content_format": "markdown",
            "kreuzberg_metadata": response_metadata
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
