"""Docling service integration for document processing."""
import asyncio
import logging
import os
import tempfile
from typing import Optional, Tuple

import httpx
from httpx import Timeout

logger = logging.getLogger("docling_integration")

# Supported file types for docling processing
SUPPORTED_FILE_TYPES = {
    ".pdf", ".docx", ".doc", ".pptx", ".ppt",
    ".xlsx", ".xls", ".html", ".htm"
}

# File types that should skip docling (already structured/text)
SKIP_DOCLING_TYPES = {
    ".txt", ".md", ".csv", ".json", ".xml", ".yaml", ".yml"
}

MAX_FILE_SIZE_BYTES = 50 * 1024 * 1024


def _get_settings():
    """Get settings from environment or local config."""
    try:
        # Try to import from the caller's context (worker or knowledgebase_ingestion)
        from core.config import settings
        logger.info(f"🔧 [DOCLING] Using settings from core.config (timeout: {settings.docling_timeout_seconds}s)")
        return settings
    except ImportError:
        try:
            # Fallback for knowledgebase_ingestion
            from knowledgebase_ingestion.core.config import settings
            logger.info(f"🔧 [DOCLING] Using settings from knowledgebase_ingestion.core.config (timeout: {settings.docling_timeout_seconds}s)")
            return settings
        except ImportError:
            # Create minimal settings from environment
            class MinimalSettings:
                docling_enabled = os.getenv("DOCLING_ENABLED", "true").lower() == "true"
                docling_timeout_seconds = int(os.getenv("DOCLING_TIMEOUT_SECONDS", "1800"))
                docling_service_url = os.getenv("DOCLING_SERVICE_URL", "http://localhost:8004")
                docling_fallback_to_raw = os.getenv("DOCLING_FALLBACK_TO_RAW", "true").lower() == "true"
            logger.info(f"🔧 [DOCLING] Using minimal settings from environment (timeout: {MinimalSettings.docling_timeout_seconds}s)")
            return MinimalSettings()


async def process_with_docling(
    file_path: str,
    original_filename: str,
    mime_type: str,
    timeout_seconds: Optional[int] = None
) -> Tuple[Optional[str], dict]:
    """
    Call docling service to convert document to markdown.
    Retries connection failures up to 3 times with exponential backoff.

    Args:
        file_path: Path to the file to process
        original_filename: Original filename
        mime_type: MIME type of the file
        timeout_seconds: Request timeout in seconds

    Returns:
        Tuple of (markdown_content, metadata) or (None, error_dict) on failure
    """
    settings = _get_settings()

    if timeout_seconds is None:
        timeout_seconds = settings.docling_timeout_seconds

    max_retries = 3
    retry_delays = [5, 15, 30]  # seconds between retries
    
    for attempt in range(max_retries):
        try:
            # Prepare multipart form data
            with open(file_path, 'rb') as f:
                files = {'file': (original_filename, f, mime_type)}

                # Use proper timeout configuration to handle long-running operations
                # Connect timeout: 30s, Read timeout: processing timeout + 60s buffer
                timeout_config = Timeout(
                    connect=30.0,
                    read=timeout_seconds + 60,
                    write=30.0,
                    pool=30.0
                )
                
                logger.info(f"🔧 [DOCLING] HTTP timeout config - Connect: 30s, Read: {timeout_seconds + 60}s, Write: 30s, Pool: 30s")
                
                async with httpx.AsyncClient(timeout=timeout_config) as client:
                    if attempt > 0:
                        logger.info(
                            f"🔄 [DOCLING] Retry attempt {attempt + 1}/{max_retries} for {original_filename}"
                        )
                    
                    logger.info(
                        f"📄 [DOCLING] Calling docling service: {settings.docling_service_url} "
                        f"for {original_filename}"
                    )

                    response = await client.post(
                        f"{settings.docling_service_url}/api/v1/docling/process",
                        files=files,
                        timeout=timeout_seconds
                    )

                    logger.info(f"📄 [DOCLING] Response status: {response.status_code}")

                    if response.status_code == 200:
                        result = response.json()

                        if result.get("success"):
                            markdown_content = result.get("content")
                            metadata = result.get("metadata", {})

                            logger.info(
                                f"✅ [DOCLING] Successfully converted {original_filename}: "
                                f"{len(markdown_content)} chars, "
                                f"{metadata.get('images_with_ocr', 0)} images OCR'd"
                            )

                            return markdown_content, metadata
                        else:
                            error = result.get("error", "Unknown error")
                            logger.warning(
                                f"⚠️ [DOCLING] Conversion failed for {original_filename}: {error}"
                            )
                            return None, {"error": error}
                    else:
                        # Handle non-200 responses with better error details
                        response_text = response.text.strip() if response.text else ""
                        if response_text:
                            error_msg = f"HTTP {response.status_code}: {response_text}"
                        else:
                            error_msg = f"HTTP {response.status_code}: Empty response from docling service"
                        
                        logger.warning(f"⚠️ [DOCLING] Request failed for {original_filename}: {error_msg}")
                        logger.debug(f"🔍 [DOCLING] Response headers: {dict(response.headers)}")
                        logger.debug(f"🔍 [DOCLING] Response status code: {response.status_code}")
                        return None, {"error": error_msg}

        except httpx.TimeoutException as e:
            # Handle different types of timeout exceptions
            error_type = type(e).__name__
            error_msg = str(e)
            
            logger.error(f"⏱️ [DOCLING_TIMEOUT] {error_type} for {original_filename}: {error_msg}")
            logger.error(f"⏱️ [DOCLING_TIMEOUT] Request details - timeout_seconds: {timeout_seconds}, attempt: {attempt + 1}/{max_retries}")
            
            # Determine which timeout caused the issue
            if "connect" in error_msg.lower():
                logger.error(f"⏱️ [DOCLING_TIMEOUT] CONNECT TIMEOUT - Could not connect to docling service")
            elif "read" in error_msg.lower():
                logger.error(f"⏱️ [DOCLING_TIMEOUT] READ TIMEOUT - Server took too long to respond")
            elif "write" in error_msg.lower():
                logger.error(f"⏱️ [DOCLING_TIMEOUT] WRITE TIMEOUT - Upload took too long")
            elif "pool" in error_msg.lower():
                logger.error(f"⏱️ [DOCLING_TIMEOUT] POOL TIMEOUT - Connection pool issue")
            else:
                logger.error(f"⏱️ [DOCLING_TIMEOUT] UNKNOWN TIMEOUT - {error_msg}")
            
            return None, {"error": f"HTTP timeout ({error_type}): {error_msg}"}

        except asyncio.TimeoutError:
            logger.warning(
                f"⚠️ [DOCLING] Timeout processing {original_filename} "
                f"(timeout={timeout_seconds}s)"
            )
            return None, {"error": "Docling processing timeout"}

        except (httpx.ConnectError, httpx.RemoteProtocolError) as e:
            # Connection errors - retry with backoff
            if attempt < max_retries - 1:
                delay = retry_delays[attempt]
                logger.warning(
                    f"⚠️ [DOCLING] Connection failed for {original_filename} (attempt {attempt + 1}/{max_retries}): {e}"
                )
                logger.info(f"⏳ [DOCLING] Retrying in {delay}s... (docling service may be busy)")
                await asyncio.sleep(delay)
                continue
            else:
                logger.warning(
                    f"⚠️ [DOCLING] All connection attempts failed for {original_filename}: {e}"
                )
                return None, {"error": f"Connection failed after {max_retries} attempts: {str(e)}"}

        except Exception as e:
            logger.warning(
                f"⚠️ [DOCLING] Error calling docling service for {original_filename}: {e}"
            )
            return None, {"error": str(e)}
    
    # Should not reach here, but just in case
    return None, {"error": "Max retries exceeded"}


async def should_use_docling_for_file(
    filename: str,
    mime_type: str,
    file_size: int
) -> bool:
    """
    Determine if docling should be used for this file.

    Checks:
    1. DOCLING_ENABLED environment variable
    2. Docling service URL is configured
    3. File is supported by docling

    Args:
        filename: Original filename
        mime_type: MIME type
        file_size: File size in bytes

    Returns:
        True if docling should be used, False otherwise
    """
    settings = _get_settings()

    # Check if docling is enabled
    if not settings.docling_enabled:
        return False

    # Check if docling service URL is configured
    if not settings.docling_service_url:
        return False

    # Get file extension
    _, ext = os.path.splitext(filename.lower())

    # Check if file type should skip docling
    if ext in SKIP_DOCLING_TYPES:
        return False

    # Check if file type is supported
    if ext not in SUPPORTED_FILE_TYPES:
        return False

    # Check file size
    if file_size > MAX_FILE_SIZE_BYTES:
        return False

    return True


async def create_markdown_temp_file(markdown_content: str) -> str:
    """
    Create a temporary markdown file from content.

    Args:
        markdown_content: The markdown content

    Returns:
        Path to the temporary markdown file
    """
    fd, temp_path = tempfile.mkstemp(suffix='.md')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(markdown_content)
        return temp_path
    except Exception as e:
        logger.error(f"❌ Failed to create markdown temp file: {e}")
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise
