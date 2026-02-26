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
        logger.info(f"🔧 [DOCLING] Using explicit DOCLING_REDIS_URL={settings.get_docling_redis_url()}")
        return settings
    except ImportError:
        try:
            # Fallback for knowledgebase_ingestion
            from knowledgebase_ingestion.core.config import settings
            logger.info(f"🔧 [DOCLING] Using settings from knowledgebase_ingestion.core.config (timeout: {settings.docling_timeout_seconds}s)")
            return settings
        except ImportError:
            # Create minimal settings from environment
            docling_redis_url = os.getenv("DOCLING_SERVE_ENG_RQ_REDIS_URL")
            if not docling_redis_url:
                raise ValueError(
                    "DOCLING_SERVE_ENG_RQ_REDIS_URL environment variable is required. "
                    "Set it to your actual Redis host (e.g., redis://redis-XXXXX.railway.internal:6379/2)"
                )

            class MinimalSettings:
                docling_enabled = os.getenv("DOCLING_ENABLED", "true").lower() == "true"
                docling_timeout_seconds = int(os.getenv("DOCLING_TIMEOUT_SECONDS", "1800"))
                docling_redis_url = os.getenv("DOCLING_SERVE_ENG_RQ_REDIS_URL")
                docling_rq_queue_name = os.getenv("DOCLING_RQ_QUEUE_NAME", "convert")
                docling_serve_eng_rq_sub_channel = os.getenv("DOCLING_SERVE_ENG_RQ_SUB_CHANNEL", "docling-results-unknown")
                docling_poll_initial_delay = int(os.getenv("DOCLING_POLL_INITIAL_DELAY", "2"))
                docling_poll_max_interval = int(os.getenv("DOCLING_POLL_MAX_INTERVAL", "30"))
                docling_fallback_to_raw = os.getenv("DOCLING_FALLBACK_TO_RAW", "true").lower() == "true"

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
    Call docling-serve via Redis Queue to convert document to JSON format.

    Args:
        presigned_url: Presigned S3 URL for direct download by docling worker
        original_filename: Original filename
        mime_type: MIME type of the file
        timeout_seconds: Job timeout in seconds

    Returns:
        Tuple of (json_content, metadata) - returns JSON format from docling
        or (None, error_dict) on failure
    """
    settings = _get_settings()

    if timeout_seconds is None:
        timeout_seconds = settings.docling_timeout_seconds

    try:
        from shared.docling_rq_client import DoclingRQClient

        logger.info(
            f"📄 [DOCLING_RQ] Enqueuing job for {original_filename} via Redis Queue (DB 2)"
        )

        # Initialize RQ client with docling-specific Redis URL (DB 2) and queue name
        # Pass timeout configurations and Railway Storage output settings from config
        docling_redis_url = settings.get_docling_redis_url()
        docling_queue_name = settings.docling_rq_queue_name

        # Get Railway Storage configuration (optional)
        # Try settings first, then fallback to direct environment variables
        railway_bucket = getattr(settings, 'railway_bucket_name', None) or os.getenv('RAILWAY_BUCKET_NAME')
        railway_region = getattr(settings, 'railway_region', None) or os.getenv('RAILWAY_REGION')
        railway_storage_url = getattr(settings, 'railway_storage_url', None) or os.getenv('RAILWAY_STORAGE_URL')
        railway_access_key = getattr(settings, 'railway_storage_access_key', None) or os.getenv('RAILWAY_STORAGE_ACCESS_KEY')
        railway_secret_key = getattr(settings, 'railway_storage_secret_key', None) or os.getenv('RAILWAY_STORAGE_SECRET_KEY')
        s3_prefix = getattr(settings, 's3_docling_prefix', 'docling-results')

        # Log Railway Storage configuration status
        logger.info(f"🔧 [RAILWAY_STORAGE_CONFIG] Bucket: {railway_bucket}")
        logger.info(f"🔧 [RAILWAY_STORAGE_CONFIG] Region: {railway_region}")
        logger.info(f"🔧 [RAILWAY_STORAGE_CONFIG] Storage URL: {railway_storage_url}")
        logger.info(f"🔧 [RAILWAY_STORAGE_CONFIG] Access Key present: {bool(railway_access_key)}")
        logger.info(f"🔧 [RAILWAY_STORAGE_CONFIG] Secret Key present: {bool(railway_secret_key)}")
        logger.info(f"🔧 [RAILWAY_STORAGE_CONFIG] S3 Prefix: {s3_prefix}")

        client = DoclingRQClient(
            redis_url=docling_redis_url,
            queue_name=docling_queue_name,
            job_timeout_minutes=settings.docling_rq_job_timeout_minutes,
            polling_timeout_seconds=settings.docling_timeout_seconds,
            poll_initial_delay=settings.docling_poll_initial_delay,
            poll_max_interval=settings.docling_poll_max_interval,
            railway_bucket_name=railway_bucket,
            railway_region=railway_region,
            railway_storage_url=railway_storage_url,
            railway_storage_access_key=railway_access_key,
            railway_storage_secret_key=railway_secret_key,
            s3_docling_prefix=s3_prefix
        )

        logger.info(
            f"⏱️  [DOCLING_CONFIG] Timeout settings: "
            f"Job={settings.docling_rq_job_timeout_minutes}min, "
            f"Polling={settings.docling_timeout_seconds}s, "
            f"Poll intervals={settings.docling_poll_initial_delay}s-{settings.docling_poll_max_interval}s"
        )

        if railway_bucket and railway_storage_url:
            logger.info(f"💾 [RAILWAY_STORAGE_CONFIG] Docling-serve will upload results to Railway Storage: {railway_bucket}/{s3_prefix}/")
        else:
            logger.info(f"💾 [REDIS_CONFIG] Docling results will be stored in Redis")

        # Enqueue job and poll for result
        json_content, metadata = await client.process_document_async(
            presigned_url,
            original_filename,
            mime_type,
            timeout_seconds=timeout_seconds
        )

        # Handle ZIP archives from docling-serve
        # Docling-serve returns results as ZipArchiveResult containing JSON or Markdown files
        # The result may be binary bytes OR a string representation of binary data (latin-1 decoded)
        is_zip = False
        zip_bytes = None

        # Check for ZIP in both binary and string representations
        if json_content:
            if isinstance(json_content, bytes):
                is_zip = json_content[:2] == b'PK'
                zip_bytes = json_content
            elif isinstance(json_content, str):
                # String representation of ZIP data (decoded as latin-1)
                # Check if it starts with 'PK' character (0x50 0x4B in ASCII/latin-1)
                is_zip = json_content.startswith('PK') or (len(json_content) > 1 and ord(json_content[0]) == 0x50 and ord(json_content[1]) == 0x4B)
                if is_zip:
                    logger.info(f"📦 [ZIP_DETECT] String content detected as ZIP - converting to bytes")
                    zip_bytes = json_content.encode('latin-1')

        if is_zip and zip_bytes:
            logger.info(f"📦 [ZIP_EXTRACT] Docling result is a ZIP archive, extracting...")
            try:
                import zipfile
                import io

                # Extract ZIP
                with zipfile.ZipFile(io.BytesIO(zip_bytes)) as zip_file:
                    file_list = zip_file.namelist()
                    logger.info(f"📋 [ZIP_CONTENTS] Files in archive ({len(file_list)}): {file_list}")

                    # Look for JSON files first, then Markdown
                    json_file = None
                    md_file = None

                    for filename in file_list:
                        if filename.endswith('.json'):
                            json_file = filename
                            break
                        elif filename.endswith('.md'):
                            md_file = filename

                    if json_file:
                        logger.info(f"✅ [ZIP_EXTRACT] Found JSON file: {json_file}")
                        json_content = zip_file.read(json_file).decode('utf-8')
                        logger.info(f"✅ [ZIP_EXTRACT] Extracted JSON - length: {len(json_content)} chars")
                    elif md_file:
                        logger.info(f"✅ [ZIP_EXTRACT] Found Markdown file: {md_file}")
                        json_content = zip_file.read(md_file).decode('utf-8')
                        logger.info(f"✅ [ZIP_EXTRACT] Extracted Markdown - length: {len(json_content)} chars")
                    else:
                        logger.error(f"❌ [ZIP_EXTRACT] No JSON or Markdown files found in archive")
                        logger.debug(f"📊 [ZIP_EXTRACT] Archive contents: {file_list}")
                        return None, {"error": "No JSON or Markdown files in docling result ZIP"}
            except Exception as e:
                logger.error(f"❌ [ZIP_EXTRACT] Failed to extract ZIP: {e}")
                import traceback
                logger.error(f"📊 [ZIP_EXTRACT] Traceback: {traceback.format_exc()}")
                return None, {"error": f"Failed to extract docling result ZIP: {str(e)}"}

        # Check if json_content is an S3 key path (not actual JSON)
        # S3 key paths start with "docling-results/" and don't start with '{' or '['
        if json_content and isinstance(json_content, str):
            if json_content.startswith('docling-results/') and not json_content.startswith('{'):
                logger.info(f"📦 [S3_DOWNLOAD] JSON stored in S3, downloading from: {json_content}")
                try:
                    # Download from Railway Storage S3
                    import boto3
                    s3_client = boto3.client(
                        's3',
                        endpoint_url=railway_storage_url,
                        aws_access_key_id=railway_access_key,
                        aws_secret_access_key=railway_secret_key,
                        region_name=railway_region or 'us-east-1'
                    )

                    # First, verify the object exists
                    logger.info(f"🔍 [S3_VERIFY] Verifying S3 object exists: {railway_bucket}/{json_content}")
                    try:
                        head_response = s3_client.head_object(
                            Bucket=railway_bucket,
                            Key=json_content
                        )
                        file_size = head_response.get('ContentLength', 0)
                        logger.info(f"✅ [S3_VERIFY] Object verified - size: {file_size} bytes")
                    except s3_client.exceptions.NoSuchKey:
                        logger.error(f"❌ [S3_VERIFY] S3 object NOT found: {railway_bucket}/{json_content}")
                        return None, {"error": f"Docling result not found in S3: {json_content}"}
                    except s3_client.exceptions.NoSuchBucket:
                        logger.error(f"❌ [S3_VERIFY] S3 bucket NOT found: {railway_bucket}")
                        return None, {"error": f"S3 bucket not found: {railway_bucket}"}

                    # Download the object
                    logger.info(f"📥 [S3_DOWNLOAD] Downloading JSON from S3...")
                    s3_response = s3_client.get_object(
                        Bucket=railway_bucket,
                        Key=json_content
                    )
                    json_content = s3_response['Body'].read().decode('utf-8')
                    logger.info(f"✅ [S3_DOWNLOAD] Successfully downloaded JSON from S3: {len(json_content)} chars")
                except Exception as e:
                    logger.error(f"❌ [S3_DOWNLOAD] Failed to download from S3: {e}")
                    import traceback
                    logger.error(f"📊 [S3_DOWNLOAD] Traceback: {traceback.format_exc()}")
                    # Return error instead of key path
                    return None, {"error": f"Failed to download from S3: {str(e)}"}

        # Log the content format and metadata
        content_format = metadata.get("content_format", "json")
        logger.info(f"📄 [DOCLING_RQ] Content format: {content_format}")
        logger.info(f"📊 [DOCLING_RQ] Metadata keys: {list(metadata.keys())}")

        logger.info(f"📋 [DOCLING_RQ] JSON content length: {len(json_content)} chars")

        # Log a safe preview - only if it looks like valid text
        if json_content and isinstance(json_content, str):
            # Check if it's likely JSON or text
            if json_content.strip().startswith(('{', '[')):
                logger.info(f"📋 [DOCLING_RQ] JSON preview (first 100 chars): {json_content[:100]}...")
            else:
                logger.info(f"📋 [DOCLING_RQ] Content preview (first 50 chars): {repr(json_content[:50])}")
        else:
            logger.warning(f"⚠️ [DOCLING_RQ] Unexpected content type: {type(json_content)}")

        logger.info(
            f"✅ [DOCLING_RQ] Successfully processed {original_filename} via Redis Queue"
        )
        return json_content, metadata

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
