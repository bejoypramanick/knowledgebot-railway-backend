"""Redis Queue client for docling-serve integration."""
import asyncio
import time
from typing import Tuple
from urllib.parse import urlparse, urlunparse
import uuid
from redis import Redis
from rq import Queue
from rq.job import Job
from shared.otel_logger import get_otel_logger

logger = get_otel_logger("docling_rq_client", "docling")


def _redact_redis_url(redis_url: str) -> str:
    """Redact sensitive info (password) from Redis URL for logging."""
    try:
        parsed = urlparse(redis_url)
        # Redact password if present
        if parsed.password:
            netloc = f"{parsed.username}:***@{parsed.hostname}"
            if parsed.port:
                netloc += f":{parsed.port}"
            redacted = urlunparse((
                parsed.scheme,
                netloc,
                parsed.path,
                parsed.params,
                parsed.query,
                parsed.fragment
            ))
            return redacted
        return redis_url
    except Exception:
        # If parsing fails, return original (shouldn't happen)
        return redis_url


class DoclingRQClient:
    """Client for interacting with docling-serve via Redis Queue."""

    def __init__(self, redis_url: str, queue_name: str = "docling"):
        """
        Initialize the RQ client.

        Args:
            redis_url: Redis connection URL (e.g., redis://host:6379/0)
            queue_name: Redis queue name (must match docling-serve worker's queue)
        """
        self.redis_conn = Redis.from_url(redis_url)
        self.queue = Queue(queue_name, connection=self.redis_conn)
        logger.info(f"🔌 [RQ_CLIENT] Initialized with Redis URL: {_redact_redis_url(redis_url)}")
        logger.info(f"🔌 [RQ_CLIENT] Using queue: {queue_name}")

    async def enqueue_document(
        self,
        presigned_url: str,
        filename: str,
        mime_type: str
    ) -> str:
        try:
            scratch_dir = "/data/scratchpad"   # confirm this matches worker mount
            task_id = str(uuid.uuid4())
            task_data = {
                "task_type": "convert",           # required – tells worker what to do
                "presigned_url": presigned_url,
                "task_id":task_id,
                "filename": filename,
                "mime_type": mime_type,
                "options": {
                    "do_ocr": False,
                    "do_table_structure": False,
                    # add more if needed, e.g.:
                    # "do_picture_description": False,
                    # "pipeline": "standard",
                },
                # optional extras the worker might use:
                # "scratch_dir": scratch_dir,     # sometimes passed here instead
            }
            job = self.queue.enqueue(
                "docling_jobkit.orchestrators.rq.worker.docling_task",
                task_data,
                options={
                    "do_ocr": True,
                    "do_table_structure": True,
                },
                scratch_dir=scratch_dir,
                job_timeout='30m',
                result_ttl=14400
            )

            return job.id

        except Exception as exc:
            # log properly in production
            print(f"Enqueue failed: {exc}")
            raise

    async def poll_job_result(
        self,
        job_id: str,
        timeout: int = 1800,
        poll_interval_initial: int = 2,
        poll_interval_max: int = 30
    ) -> Tuple[str, dict]:
        """
        Poll for job completion with exponential backoff.

        Args:
            job_id: RQ job ID to poll
            timeout: Maximum time to wait in seconds (default 30 minutes)
            poll_interval_initial: Initial poll interval in seconds
            poll_interval_max: Maximum poll interval in seconds

        Returns:
            Tuple of (markdown_content, metadata)

        Raises:
            TimeoutError: If job doesn't complete within timeout
            Exception: If job fails
        """
        start_time = time.time()
        interval = poll_interval_initial

        logger.info(f"⏳ [RQ_POLL] Starting poll for job: {job_id} (timeout: {timeout}s)")

        while True:
            elapsed = time.time() - start_time
            if elapsed > timeout:
                logger.error(f"❌ [RQ_TIMEOUT] Job {job_id} timed out after {timeout}s")
                raise TimeoutError(f"Job {job_id} timeout after {timeout}s")

            try:
                job = Job.fetch(job_id, connection=self.redis_conn)

                if job.is_finished:
                    result = job.result
                    logger.info(f"✅ [RQ_SUCCESS] Job {job_id} completed successfully")

                    # Validate result structure
                    if isinstance(result, dict):
                        markdown = result.get('markdown', '')
                        metadata = result.get('metadata', {})
                    else:
                        logger.warning(f"⚠️ [RQ_RESULT] Unexpected result type: {type(result)}")
                        markdown = str(result)
                        metadata = {}

                    logger.info(f"📝 [RQ_RESULT] Markdown length: {len(markdown)} chars")
                    logger.info(f"📊 [RQ_METADATA] Keys: {list(metadata.keys())}")

                    return markdown, metadata

                if job.is_failed:
                    exc_info = job.exc_info or "Unknown error"
                    logger.error(f"❌ [RQ_FAILED] Job {job_id} failed: {exc_info}")
                    raise Exception(f"Job failed: {exc_info}")

                # Job still processing
                logger.debug(f"⏳ [RQ_POLL] Job {job_id} still processing... (elapsed: {elapsed:.1f}s)")

            except Exception as e:
                # Re-raise job failures, but not polling errors
                if "Job failed" in str(e) or "timeout" in str(e).lower():
                    raise
                logger.warning(f"⚠️ [RQ_POLL] Polling error: {e}")

            # Exponential backoff
            await asyncio.sleep(interval)
            interval = min(interval * 1.5, poll_interval_max)

    async def process_document_async(
        self,
        presigned_url: str,
        filename: str,
        mime_type: str,
        timeout_seconds: int = 1800
    ) -> Tuple[str, dict]:
        """
        High-level method: enqueue job, poll for result, return content.

        Args:
            presigned_url: Presigned S3 URL
            filename: Original filename
            mime_type: MIME type
            timeout_seconds: Timeout for polling

        Returns:
            Tuple of (markdown_content, metadata)
        """
        try:
            # Enqueue the job
            job_id = await self.enqueue_document(presigned_url, filename, mime_type)

            # Poll for result
            markdown, metadata = await self.poll_job_result(
                job_id,
                timeout=timeout_seconds
            )

            return markdown, metadata

        except Exception as e:
            logger.error(f"❌ [RQ_PROCESS] Error processing {filename}: {e}")
            raise
