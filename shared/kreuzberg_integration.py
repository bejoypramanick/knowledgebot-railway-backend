"""
Kreuzberg Document Intelligence Integration
Routes extraction through the dedicated Redis-driven Rust Kreuzberg worker.
"""
import asyncio
import json
import time
import os
import os.path
from typing import Tuple, Dict, Any, Optional
from shared.extraction_worker_client import ExtractionWorkerClient
from shared.otel_logger import get_otel_logger
from shared.s3_file_storage import s3_file_storage

logger = get_otel_logger("kreuzberg_integration", "shared")

KREUZBERG_REDIS_TIMEOUT = float(os.environ.get("KREUZBERG_REDIS_TIMEOUT", "300.0"))
KREUZBERG_POLL_INTERVAL = float(os.environ.get("KREUZBERG_POLL_INTERVAL", "1.0"))


async def _download_s3_text(s3_key: str) -> Optional[str]:
    success, payload = await s3_file_storage.download_file(s3_key)
    if not success:
        return None
    return payload.decode("utf-8", errors="replace")


async def _download_s3_json(s3_key: str) -> Any:
    success, payload = await s3_file_storage.download_file(s3_key)
    if not success:
        return None
    return json.loads(payload.decode("utf-8"))


def _json_safe_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(k): _json_safe_value(v) for k, v in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe_value(v) for v in value]
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    return str(value)


async def process_with_kreuzberg(
    s3_key: str,
    original_filename: str,
    mime_type: str,
    worker_type: str = "file",
    source_id: Optional[str] = None,
    source_name: Optional[str] = None
) -> Tuple[Optional[str], Dict[str, Any]]:
    """
    Send a document to the dedicated Kreuzberg extraction worker.
    Returns (markdown_content, metadata_dict).
    """
    start_time = time.time()
    reply_channel = f"kreuzberg_extraction_results:{source_id or original_filename}:{int(start_time * 1000)}"
    client = ExtractionWorkerClient()
    # IMPORTANT: artifact_prefix must be unique per extraction job. For web crawling we often run
    # multiple page extractions under the same website_id; using only source_id would cause S3
    # key collisions and missing/overwritten artifacts.
    base_name = os.path.basename(original_filename or "document")
    base_stem = os.path.splitext(base_name)[0] or "document"
    artifact_prefix = f"processing/processed/{source_id or base_stem}/{base_stem}_{int(start_time * 1000)}"
    document_id = _json_safe_value(source_id or original_filename)

    logger.info(f"[KREUZBERG] Queueing extraction for {original_filename} via Redis worker")

    try:
        job = client.create_job(
            document_id=document_id,
            worker_type=worker_type,
            s3_key=s3_key,
            original_filename=original_filename,
            mime_type=mime_type,
            artifact_prefix=artifact_prefix,
            reply_channel=reply_channel,
        )

        published = await asyncio.to_thread(client.publish_job, job)
        if not published:
            return None, {"error": "Failed to publish Kreuzberg extraction job"}

        timeout_at = time.time() + KREUZBERG_REDIS_TIMEOUT
        result = None
        while time.time() < timeout_at:
            result = await asyncio.to_thread(client.get_result, 1, reply_channel, worker_type)
            if result:
                break
            await asyncio.sleep(KREUZBERG_POLL_INTERVAL)

        if not result:
            return None, {"error": f"Kreuzberg extraction timed out after {int(KREUZBERG_REDIS_TIMEOUT)}s"}
        if result.get("status") != "completed":
            return None, {"error": result.get("error") or "Kreuzberg extraction failed"}

        manifest_s3_key = result.get("manifest_s3_key")
        manifest = await _download_s3_json(manifest_s3_key) if manifest_s3_key else None
        if not manifest:
            return None, {"error": f"Failed to download extraction manifest from S3: {manifest_s3_key}"}

        markdown_s3_key = manifest.get("markdown_s3_key")
        markdown_content = await _download_s3_text(markdown_s3_key) if markdown_s3_key else None
        if not markdown_content:
            return None, {"error": f"Failed to download markdown artifact from S3: {markdown_s3_key}"}

        chunks = []
        chunks_s3_key = manifest.get("chunks_s3_key")
        if chunks_s3_key:
            chunks = await _download_s3_json(chunks_s3_key) or []

        tables = []
        tables_s3_key = manifest.get("tables_s3_key")
        if tables_s3_key:
            tables = await _download_s3_json(tables_s3_key) or []

        processing_time_ms = int((time.time() - start_time) * 1000)
        logger.info(f"✅ [KREUZBERG] Done in {processing_time_ms}ms — {len(markdown_content)} characters")

        return markdown_content, {
            "processing_time_ms": processing_time_ms,
            "content_format": "markdown",
            "chunks": chunks,
            "tables": tables,
            "markdown_s3_key": markdown_s3_key,
            "chunks_s3_key": chunks_s3_key,
            "tables_s3_key": tables_s3_key,
            "manifest_s3_key": manifest_s3_key,
            "kreuzberg_metadata": manifest.get("metadata", {}),
            "page_count": manifest.get("metadata", {}).get("page_count", 0),
            "table_count": manifest.get("metadata", {}).get("table_count", len(tables)),
        }

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
