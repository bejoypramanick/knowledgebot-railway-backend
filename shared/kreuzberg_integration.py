"""
Kreuzberg Document Intelligence Integration
Provides a fast, synchronous REST API call to the Kreuzberg container.
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

KREUZBERG_API_URL = os.environ.get("KREUZBERG_API_URL", "http://kreuzberg:8000")
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
            if last_err is not None:
                raise last_err
            raise Exception(f"KREUZBERG_RETRY_FAILED: Max retries reached for {func.__name__} without specific error recorded.")
        return wrapper
    return decorator

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


@retry_on_connection_error(max_retries=10, delay=3.0)
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
    
    # 2. DNS & Connectivity Diagnostics
    # We resolve the hostname just for logging/debugging purposes.
    # The actual connection attempt will handle the fallback.
    hostname = endpoint.split("//")[-1].split(":")[0].split("/")[0]
    try:
        import socket
        ip_addr = socket.gethostbyname(hostname)
        logger.info(f"🌐 [KREUZBERG_DNS] Resolved {hostname} to {ip_addr}")
    except Exception as dns_err:
        logger.warning(f"⚠️ [KREUZBERG_DNS] Could not resolve hostname {hostname}: {dns_err}")

    logger.info("=" * 80)

    # 3. Download file from S3 into memory
    file_bytes = await download_file_from_s3(presigned_url)

    # 4. Prepare Kreuzberg API Request
    # We define a helper for the actual POST to allow for internal fallbacks
    async def perform_request(target_url: str) -> httpx.Response:
        logger.info(f"[KREUZBERG] Attempting extraction request to {target_url}...")
        async with httpx.AsyncClient(timeout=KREUZBERG_API_TIMEOUT) as client:
            # Official API spec uses 'files' (plural)
            files_payload = [('files', (original_filename, file_bytes, mime_type))]
            
            unified_config = {
                "enable_quality_processing": True,
                "output_format": "markdown",
                "layout": {"preset": "fast"}
            }

        data = {
            "config": json.dumps(unified_config),
            "output_format": "markdown"
        }
            
        return await client.post(target_url, files=files_payload, data=data)

    response: Optional[httpx.Response] = None
    last_err: Optional[Exception] = None

    try:
        try:
            response = await perform_request(endpoint)
        except (httpx.RequestError, httpx.NetworkError) as conn_err:
            # TRIPLE-STACK FALLBACK:
            # 1. Primary endpoint failed.
            # 2. Try simple service discovery (http://kreuzberg:8000)
            
            logger.warning(f"⚠️ [KREUZBERG_CONNECT_FAIL] Primary endpoint {endpoint} failed: {type(conn_err).__name__}: {conn_err}")
            
            # Sequence of fallbacks to try
            fallbacks = []
            if "kreuzberg.railway.internal" in endpoint:
                fallbacks.append(endpoint.replace("kreuzberg.railway.internal", "kreuzberg"))
            
            response = None
            last_err = conn_err
            
            for fallback_url in fallbacks:
                try:
                    logger.info(f"🔄 [KREUZBERG_FALLBACK] Attempting fallback to {fallback_url}...")
                    response = await perform_request(fallback_url)
                    if response is not None:
                        endpoint = fallback_url 
                        break
                except (httpx.RequestError, httpx.NetworkError) as fb_err:
                    logger.warning(f"⚠️ [KREUZBERG_FALLBACK_FAIL] Fallback {fallback_url} failed: {type(fb_err).__name__}: {fb_err}")
                    last_err = fb_err
            
            if response is None:
                if last_err:
                    raise last_err
                else:
                    raise Exception("Failed to connect to Kreuzberg and no fallbacks succeeded.")

        if response is None:
            return None, {"error": "No response received from Kreuzberg."}

        if response.status_code != 200:
            logger.error(f"[KREUZBERG] API returned error {response.status_code}: {response.text}")
            return None, {"error": f"API Error {response.status_code}: {response.text}"}
            
        result = response.json()
            
        # 3. Parse and normalize response
        # Kreuzberg returns an object with 'content' (markdown) and 'tables' (structured data)
        # If it returns a list, take the first element (the only file we sent)
        if isinstance(result, list) and len(result) > 0:
            result = result[0]
            
        # Debug logging for empty chunks
        if not result.get("chunks"):
            logger.warning(f"⚠️ [KREUZBERG_DEBUG] No chunks returned. Keys in result: {list(result.keys())}")
            if "content" in result:
                logger.info(f"   Content length: {len(result['content'])} characters")
            logger.info(f"   Full Result Structure: {json.dumps({k: str(v)[:100] for k, v in result.items()}, indent=2)}")
            
        processing_time_ms = int((time.time() - start_time) * 1000)
            
        # 4. Standard Markdown Output
        # Kreuzberg returns an object with 'content' (markdown) and 'tables' (structured data)
        # We now use 'content' directly and let Chonkie handle chunking.
        markdown_content = result.get("content", "")
        if not markdown_content and "text" in result:
            markdown_content = result.get("text", "")
            
        tables = result.get("tables", [])
        chunks = result.get("chunks", [])
        response_metadata = result.get("metadata", {})
        
        if tables:
            logger.info(f"[KREUZBERG] Found {len(tables)} tables in document.")

        metadata = {
            "processing_time_ms": processing_time_ms,
            "images_extracted": 0,
            "images_with_ocr": 0,
            "content_format": "markdown",
            "kreuzberg_metadata": response_metadata,
            "tables_processed": len(tables),
            "chunks": chunks  # Pass chunks (with embeddings) for pgvector storage
        }

        logger.info(f"✅ [KREUZBERG] Extraction successful in {processing_time_ms}ms (Got {len(chunks)} chunks)")
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
