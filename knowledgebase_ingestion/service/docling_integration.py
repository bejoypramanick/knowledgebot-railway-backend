"""Docling service integration for knowledgebase ingestion."""
import asyncio
import logging
import os
import tempfile
from typing import Optional, Tuple

import httpx

from knowledgebase_ingestion.core.config import settings
from docling_service.utils.validation import should_use_docling

logger = logging.getLogger("ingestion_service")


async def process_with_docling(
    file_path: str,
    original_filename: str,
    mime_type: str,
    timeout_seconds: Optional[int] = None
) -> Tuple[Optional[str], dict]:
    """
    Call docling service to convert document to markdown.

    Args:
        file_path: Path to the file to process
        original_filename: Original filename
        mime_type: MIME type of the file
        timeout_seconds: Request timeout in seconds

    Returns:
        Tuple of (markdown_content, metadata) or (None, error_dict) on failure
    """
    if timeout_seconds is None:
        timeout_seconds = settings.docling_timeout_seconds

    try:
        # Prepare multipart form data
        with open(file_path, 'rb') as f:
            files = {'file': (original_filename, f, mime_type)}

            async with httpx.AsyncClient(timeout=timeout_seconds + 10) as client:
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
                    error_msg = f"HTTP {response.status_code}: {response.text}"
                    logger.warning(f"⚠️ [DOCLING] Request failed for {original_filename}: {error_msg}")
                    return None, {"error": error_msg}

    except asyncio.TimeoutError:
        logger.warning(
            f"⚠️ [DOCLING] Timeout processing {original_filename} "
            f"(timeout={timeout_seconds}s)"
        )
        return None, {"error": "Docling processing timeout"}

    except Exception as e:
        logger.warning(
            f"⚠️ [DOCLING] Error calling docling service for {original_filename}: {e}"
        )
        return None, {"error": str(e)}


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
    # Check if docling is enabled
    if not settings.docling_enabled:
        return False

    # Check if docling service URL is configured
    if not settings.docling_service_url:
        return False

    # Check if file type is supported
    if not should_use_docling(filename, mime_type, file_size):
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
