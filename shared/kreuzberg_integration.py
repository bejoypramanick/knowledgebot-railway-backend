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
from shared.tenant_context import resolve_tenant_scope

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
    timings_ms: Dict[str, int] = {}
    tenant_scope = resolve_tenant_scope()
    reply_channel = (
        f"kreuzberg_extraction_results:tenant:{tenant_scope}:"
        f"{source_id or original_filename}:{int(start_time * 1000)}"
    )
    client = ExtractionWorkerClient()
    # IMPORTANT: artifact_prefix must be unique per extraction job. For web crawling we often run
    # multiple page extractions under the same website_id; using only source_id would cause S3
    # key collisions and missing/overwritten artifacts.
    base_name = os.path.basename(original_filename or "document")
    base_stem = os.path.splitext(base_name)[0] or "document"
    artifact_prefix = f"processing/processed/{source_id or base_stem}/{base_stem}_{int(start_time * 1000)}"
    document_id = _json_safe_value(source_id or original_filename)

    logger.info(
        f"[KREUZBERG] Queueing extraction for {original_filename} via Redis worker "
        f"(worker_type={worker_type} mime_type={mime_type} timeout_s={int(KREUZBERG_REDIS_TIMEOUT)})"
    )

    try:
        create_job_started = time.time()
        job = client.create_job(
            document_id=document_id,
            worker_type=worker_type,
            s3_key=s3_key,
            original_filename=original_filename,
            mime_type=mime_type,
            artifact_prefix=artifact_prefix,
            reply_channel=reply_channel,
        )
        timings_ms["create_job_ms"] = int((time.time() - create_job_started) * 1000)

        publish_started = time.time()
        published = await asyncio.to_thread(client.publish_job, job)
        timings_ms["publish_job_ms"] = int((time.time() - publish_started) * 1000)
        if not published:
            return None, {
                "error": "Failed to publish Kreuzberg extraction job",
                "timings_ms": timings_ms,
            }

        timeout_at = time.time() + KREUZBERG_REDIS_TIMEOUT
        result = None
        poll_attempts = 0
        wait_started = time.time()
        while time.time() < timeout_at:
            poll_attempts += 1
            result = await asyncio.to_thread(client.get_result, 1, reply_channel, worker_type)
            if result:
                break
            await asyncio.sleep(KREUZBERG_POLL_INTERVAL)
        timings_ms["wait_for_result_ms"] = int((time.time() - wait_started) * 1000)
        timings_ms["poll_attempts"] = poll_attempts

        if not result:
            logger.error(
                f"❌ [KREUZBERG_TIMEOUT] No extraction result received for {original_filename} "
                f"after {timings_ms['wait_for_result_ms']}ms "
                f"(poll_attempts={poll_attempts} reply_channel={reply_channel} "
                f"artifact_prefix={artifact_prefix})"
            )
            return None, {
                "error": f"Kreuzberg extraction timed out after {int(KREUZBERG_REDIS_TIMEOUT)}s",
                "timings_ms": timings_ms,
                "reply_channel": reply_channel,
                "artifact_prefix": artifact_prefix,
            }
        if result.get("status") != "completed":
            logger.error(
                f"❌ [KREUZBERG_RESULT_ERROR] Extraction failed for {original_filename} "
                f"status={result.get('status')} error={result.get('error')} "
                f"job_id={result.get('job_id')} timings={timings_ms}"
            )
            return None, {
                "error": result.get("error") or "Kreuzberg extraction failed",
                "timings_ms": timings_ms,
                "job_id": result.get("job_id"),
            }

        manifest_s3_key = result.get("manifest_s3_key")
        manifest_started = time.time()
        manifest = await _download_s3_json(manifest_s3_key) if manifest_s3_key else None
        timings_ms["download_manifest_ms"] = int((time.time() - manifest_started) * 1000)
        if not manifest:
            logger.error(
                f"❌ [KREUZBERG_MANIFEST_DOWNLOAD_FAILED] Could not download manifest "
                f"for {original_filename} manifest_s3_key={manifest_s3_key} "
                f"job_id={result.get('job_id')} timings={timings_ms}"
            )
            return None, {
                "error": f"Failed to download extraction manifest from S3: {manifest_s3_key}",
                "timings_ms": timings_ms,
                "job_id": result.get("job_id"),
                "manifest_s3_key": manifest_s3_key,
            }

        markdown_s3_key = manifest.get("markdown_s3_key")
        markdown_started = time.time()
        markdown_content = await _download_s3_text(markdown_s3_key) if markdown_s3_key else None
        timings_ms["download_markdown_ms"] = int((time.time() - markdown_started) * 1000)
        if not markdown_content:
            logger.error(
                f"❌ [KREUZBERG_MARKDOWN_DOWNLOAD_FAILED] Could not download markdown "
                f"for {original_filename} markdown_s3_key={markdown_s3_key} "
                f"job_id={result.get('job_id')} timings={timings_ms}"
            )
            return None, {
                "error": f"Failed to download markdown artifact from S3: {markdown_s3_key}",
                "timings_ms": timings_ms,
                "job_id": result.get("job_id"),
                "markdown_s3_key": markdown_s3_key,
            }

        chunks = []
        chunks_s3_key = manifest.get("chunks_s3_key")
        if chunks_s3_key:
            chunks_started = time.time()
            chunks = await _download_s3_json(chunks_s3_key) or []
            timings_ms["download_chunks_ms"] = int((time.time() - chunks_started) * 1000)

        tables = []
        tables_s3_key = manifest.get("tables_s3_key")
        if tables_s3_key:
            tables_started = time.time()
            tables = await _download_s3_json(tables_s3_key) or []
            timings_ms["download_tables_ms"] = int((time.time() - tables_started) * 1000)

        processing_time_ms = int((time.time() - start_time) * 1000)
        timings_ms["total_ms"] = processing_time_ms
        logger.info(
            f"✅ [KREUZBERG] Done in {processing_time_ms}ms — {len(markdown_content)} characters "
            f"(job_id={result.get('job_id')} poll_attempts={poll_attempts} timings={timings_ms})"
        )

        return markdown_content, {
            "processing_time_ms": processing_time_ms,
            "timings_ms": timings_ms,
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
        timings_ms["total_ms"] = int((time.time() - start_time) * 1000)
        logger.error(
            f"❌ [KREUZBERG] Extraction failed for {original_filename}: {e} "
            f"(worker_type={worker_type} mime_type={mime_type} timings={timings_ms})"
        )
        import traceback
        logger.error(traceback.format_exc())
        return None, {"error": str(e), "timings_ms": timings_ms}

async def should_use_kreuzberg_for_file(filename: str, mime_type: str, file_size: int = 0) -> bool:
    """Determine if a file should be sent to Kreuzberg."""
    # Kreuzberg handles many formats. As a safe bet, we route typical documents.
    supported_extensions = {
        '.pdf', '.docx', '.doc', '.pptx', '.ppt', '.xlsx', '.xls', 
        '.html', '.htm', '.rtf', '.epub', '.csv',
        '.png', '.jpg', '.jpeg', '.webp', '.gif', '.bmp', '.tif', '.tiff', '.svg'
    }
    
    ext = os.path.splitext(filename.lower())[1]
    if ext in supported_extensions:
        return True
        
    supported_mimes = [
        'application/pdf',
        'application/vnd.openxmlformats-officedocument',
        'application/msword',
        'text/html',
        'image/'
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
