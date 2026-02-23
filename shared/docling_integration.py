"""Docling service integration for document processing."""
import asyncio
import os
import tempfile
import time
from typing import Optional, Tuple

from shared.otel_logger import get_otel_logger

logger = get_otel_logger("docling_integration", "docling")

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
        logger.info(f"🔧 [DOCLING] Using explicit DOCLING_REDIS_URL={settings.get_docling_redis_url}")
        return settings
    except ImportError:
        try:
            # Fallback for knowledgebase_ingestion
            from knowledgebase_ingestion.core.config import settings
            logger.info(f"🔧 [DOCLING] Using settings from knowledgebase_ingestion.core.config (timeout: {settings.docling_timeout_seconds}s)")
            return settings
        except ImportError:
            # Create minimal settings from environment
            docling_redis_url = os.getenv("DOCLING_REDIS_URL")
            if not docling_redis_url:
                raise ValueError(
                    "DOCLING_REDIS_URL environment variable is required. "
                    "Set it to: redis://redis.railway.internal:6379/2"
                )

            class MinimalSettings:
                docling_enabled = os.getenv("DOCLING_ENABLED", "true").lower() == "true"
                docling_timeout_seconds = int(os.getenv("DOCLING_TIMEOUT_SECONDS", "1800"))
                docling_redis_url = os.getenv("DOCLING_REDIS_URL")
                docling_rq_queue_name = os.getenv("DOCLING_RQ_QUEUE_NAME", "docling")
                docling_poll_initial_delay = int(os.getenv("DOCLING_POLL_INITIAL_DELAY", "2"))
                docling_poll_max_interval = int(os.getenv("DOCLING_POLL_MAX_INTERVAL", "30"))
                docling_fallback_to_raw = os.getenv("DOCLING_FALLBACK_TO_RAW", "true").lower() == "true"

                @property
                def get_docling_redis_url(self) -> str:
                    """Get explicit docling Redis URL."""
                    return self.docling_redis_url

            logger.info(f"🔧 [DOCLING] Using minimal settings from environment (timeout: {MinimalSettings.docling_timeout_seconds}s)")
            logger.info(f"🔧 [DOCLING] Using explicit DOCLING_REDIS_URL={docling_redis_url}")
            return MinimalSettings()


async def process_with_docling(
    presigned_url: str,
    original_filename: str,
    mime_type: str,
    timeout_seconds: Optional[int] = None
) -> Tuple[Optional[str], dict]:
    """
    Call docling-serve via Redis Queue to convert document to markdown.

    Args:
        presigned_url: Presigned S3 URL for direct download by docling worker
        original_filename: Original filename
        mime_type: MIME type of the file
        timeout_seconds: Job timeout in seconds

    Returns:
        Tuple of (markdown_content, metadata) or (None, error_dict) on failure
    """
    settings = _get_settings()

    if timeout_seconds is None:
        timeout_seconds = settings.docling_timeout_seconds

    try:
        from shared.docling_rq_client import DoclingRQClient

        logger.info(
            f"📄 [DOCLING_RQ] Enqueuing job for {original_filename} via Redis Queue (DB 2)"
        )

        # Initialize RQ client with docling-specific Redis URL (DB 2)
        docling_redis_url = settings.get_docling_redis_url if hasattr(settings, 'get_docling_redis_url') else settings.redis_url.replace('/0', '/2') if settings.redis_url.endswith('/0') else settings.redis_url + '/2'
        client = DoclingRQClient(docling_redis_url)

        # Enqueue job and poll for result
        markdown_content, metadata = await client.process_document_async(
            presigned_url,
            original_filename,
            mime_type,
            timeout_seconds=timeout_seconds
        )

        # Log the content format and metadata
        content_format = metadata.get("content_format", "markdown")
        logger.info(f"📄 [DOCLING_RQ] Content format: {content_format}")
        logger.info(f"📊 [DOCLING_RQ] Metadata keys: {list(metadata.keys())}")

        if content_format == "json":
            logger.info(f"📋 [DOCLING_RQ] JSON content length: {len(markdown_content)} chars")
            logger.info(f"📋 [DOCLING_RQ] JSON preview: {markdown_content[:200]}...")
        else:
            logger.info(f"📝 [DOCLING_RQ] Markdown content length: {len(markdown_content)} chars")
            logger.info(f"📝 [DOCLING_RQ] Markdown preview: {markdown_content[:200]}...")

        logger.info(
            f"✅ [DOCLING_RQ] Successfully processed {original_filename} via Redis Queue"
        )
        return markdown_content, metadata

    except TimeoutError as e:
        logger.error(f"⏱️ [DOCLING_RQ] Timeout: {e}")
        return None, {"error": f"Timeout: {str(e)}"}

    except Exception as e:
        logger.error(f"❌ [DOCLING_RQ] Error processing {original_filename}: {e}")
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
    2. File is supported by docling
    3. File size is within limits

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
        logger.info(f"🔍 [DOCLING] Docling disabled in settings, skipping for {filename}")
        return False

    # Get file extension
    _, ext = os.path.splitext(filename.lower())

    # Check if file type should skip docling
    if ext in SKIP_DOCLING_TYPES:
        logger.info(f"🔍 [DOCLING] File type {ext} marked to skip docling for {filename}")
        return False

    # Check if file type is supported
    if ext not in SUPPORTED_FILE_TYPES:
        logger.info(f"🔍 [DOCLING] File type {ext} not supported by docling for {filename}")
        return False

    # Check file size
    if file_size > MAX_FILE_SIZE_BYTES:
        logger.warning(f"⚠️ [DOCLING] File size {file_size} exceeds limit {MAX_FILE_SIZE_BYTES} for {filename}")
        return False

    logger.info(f"✅ [DOCLING] File {filename} (ext: {ext}, size: {file_size}) will use docling")
    return True


def create_markdown_temp_file(markdown_content: str) -> str:
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
        logger.error(f" Failed to create markdown temp file: {e}")
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise


def create_json_temp_file(json_content: str) -> str:
    """Create a temporary file with JSON content for Gemini FileStore."""
    fd, temp_path = tempfile.mkstemp(suffix='.json')
    try:
        with os.fdopen(fd, 'w', encoding='utf-8') as f:
            f.write(json_content)
        logger.info(f" [JSON_TEMP] Created JSON temp file: {temp_path}")
        return temp_path
    except Exception as e:
        logger.error(f" Failed to create JSON temp file: {e}")
        if os.path.exists(temp_path):
            os.unlink(temp_path)
        raise
