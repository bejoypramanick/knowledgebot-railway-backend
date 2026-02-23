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

    def __init__(
        self,
        redis_url: str,
        queue_name: str = "docling",
        job_timeout_minutes: int = 60,
        polling_timeout_seconds: int = 3600,
        poll_initial_delay: int = 2,
        poll_max_interval: int = 60,
        railway_bucket_name: str = None,
        railway_region: str = None,
        railway_storage_url: str = None,
        railway_storage_access_key: str = None,
        railway_storage_secret_key: str = None,
        s3_docling_prefix: str = "docling-results"
    ):
        """
        Initialize the RQ client with configurable timeouts and Railway Storage output.

        Args:
            redis_url: Redis connection URL (e.g., redis://host:6379/0)
            queue_name: Redis queue name (must match docling-serve worker's queue)
            job_timeout_minutes: RQ job timeout in minutes (default 60 minutes = 1 hour)
            polling_timeout_seconds: Max time to poll for results in seconds (default 3600 = 1 hour)
            poll_initial_delay: Initial polling interval in seconds (default 2)
            poll_max_interval: Maximum polling interval in seconds (default 60)
            railway_bucket_name: Railway Storage bucket for docling output (RAILWAY_BUCKET_NAME)
            railway_region: Railway Storage region (RAILWAY_REGION)
            railway_storage_url: Railway Storage S3-compatible endpoint URL (RAILWAY_STORAGE_URL)
            railway_storage_access_key: Railway Storage access key (RAILWAY_STORAGE_ACCESS_KEY)
            railway_storage_secret_key: Railway Storage secret key (RAILWAY_STORAGE_SECRET_KEY)
            s3_docling_prefix: S3 key prefix for docling outputs (default docling-results)
        """
        self.redis_conn = Redis.from_url(redis_url)
        self.queue = Queue(queue_name, connection=self.redis_conn)
        self.job_timeout_minutes = job_timeout_minutes
        self.polling_timeout_seconds = polling_timeout_seconds
        self.poll_initial_delay = poll_initial_delay
        self.poll_max_interval = poll_max_interval

        # Railway Storage configuration for docling output
        self.railway_bucket_name = railway_bucket_name
        self.railway_region = railway_region
        self.railway_storage_url = railway_storage_url
        self.railway_storage_access_key = railway_storage_access_key
        self.railway_storage_secret_key = railway_storage_secret_key
        self.s3_docling_prefix = s3_docling_prefix

        logger.info(f"🔌 [RQ_CLIENT] Initialized with Redis URL: {_redact_redis_url(redis_url)}")
        logger.info(f"🔌 [RQ_CLIENT] Using queue: {queue_name}")
        logger.info(f"⏱️  [RQ_CLIENT] Job timeout: {job_timeout_minutes} minutes")
        logger.info(f"⏱️  [RQ_CLIENT] Polling timeout: {polling_timeout_seconds} seconds ({polling_timeout_seconds/60:.1f} minutes)")
        logger.info(f"⏱️  [RQ_CLIENT] Poll intervals: {poll_initial_delay}s initial, {poll_max_interval}s max")

        # Log Railway Storage configuration (for debugging)
        logger.info(f"💾 [RAILWAY_STORAGE_DEBUG] Bucket: {railway_bucket_name}")
        logger.info(f"💾 [RAILWAY_STORAGE_DEBUG] Region: {railway_region}")
        logger.info(f"💾 [RAILWAY_STORAGE_DEBUG] URL: {railway_storage_url}")
        logger.info(f"💾 [RAILWAY_STORAGE_DEBUG] Access Key present: {bool(railway_storage_access_key)}")
        logger.info(f"💾 [RAILWAY_STORAGE_DEBUG] Secret Key present: {bool(railway_storage_secret_key)}")

        if railway_bucket_name and railway_storage_url and railway_storage_access_key and railway_storage_secret_key:
            logger.info(f"💾 [RAILWAY_STORAGE] Docling will upload results to: Railway Storage {railway_bucket_name}/{s3_docling_prefix}/ (region: {railway_region})")
        else:
            missing = []
            if not railway_bucket_name:
                missing.append("bucket")
            if not railway_storage_url:
                missing.append("storage_url")
            if not railway_storage_access_key:
                missing.append("access_key")
            if not railway_storage_secret_key:
                missing.append("secret_key")
            logger.warning(f"⚠️  [RAILWAY_STORAGE] Missing credentials ({', '.join(missing)}) - docling results will be stored in Redis")

    async def enqueue_document(
        self,
        presigned_url: str,
        filename: str,
        mime_type: str
    ) -> str:
        """
        Enqueue a document conversion job to the docling RQ queue.

        Args:
            presigned_url: Presigned S3 URL for direct download by docling worker
            filename: Original filename
            mime_type: MIME type of the file

        Returns:
            job_id: RQ job ID for polling results

        Raises:
            Exception: If enqueuing fails
        """
        try:
            scratch_dir = "/data/scratchpad"
            task_id = str(uuid.uuid4())

            # Build task data according to docling-serve RQ Task schema
            # The RQ worker expects:
            # - Top level: to_formats, return_as_file, target
            # - options.pipeline_options: Docling conversion settings (NOT export_options)
            task_data = {
                "task_id": task_id,
                "task_type": "convert",
                "sources": [
                    {
                        "kind": "http",
                        "url": presigned_url
                    }
                ],
                # Top-level orchestrator parameters
                "to_formats": ["json"],      # Request JSON format
                "return_as_file": False     # Return raw result, not file
                # Pipeline options for Docling Engine
                
            }

            # Add Railway Storage target if configured - docling-serve will upload result directly to Railway Storage
            # Must match docling_jobkit.datamodel.DoclingJobkitS3Target schema
            # Validate that ALL required S3 credentials are present
            has_all_s3_creds = (
                self.railway_bucket_name and
                self.railway_storage_url and
                self.railway_storage_access_key and
                self.railway_storage_secret_key
            )

            if has_all_s3_creds:
                task_data["target"] = {
                    "kind": "s3",
                    "bucket": self.railway_bucket_name,
                    "key_prefix": f"{self.s3_docling_prefix}/{task_id}/",
                    "region": self.railway_region,
                    "endpoint": self.railway_storage_url,
                    "access_key": self.railway_storage_access_key,
                    "secret_key": self.railway_storage_secret_key
                }
                logger.info(f"📍 [RAILWAY_STORAGE_TARGET] Task {task_id} will output to: {self.railway_bucket_name}/{self.s3_docling_prefix}/{task_id}/")
            else:
                # Log which credentials are missing for debugging
                missing_creds = []
                if not self.railway_bucket_name:
                    missing_creds.append("RAILWAY_BUCKET_NAME")
                if not self.railway_storage_url:
                    missing_creds.append("RAILWAY_STORAGE_URL")
                if not self.railway_storage_access_key:
                    missing_creds.append("RAILWAY_STORAGE_ACCESS_KEY")
                if not self.railway_storage_secret_key:
                    missing_creds.append("RAILWAY_STORAGE_SECRET_KEY")

                if missing_creds:
                    logger.warning(f"⚠️  [RAILWAY_STORAGE] Missing S3 credentials: {', '.join(missing_creds)} - Task {task_id} will output to Redis instead")
                else:
                    logger.info(f"📍 [REDIS_TARGET] Task {task_id} will output to Redis")


            # Enqueue to docling_jobkit's RQ worker function
            # Note: conversion_manager, orchestrator_config, and scratch_dir
            # are automatically injected by CustomRQWorker.perform_job() into job.kwargs

            # Format job timeout: convert minutes to string like "60m" or "90m"
            job_timeout_str = f"{self.job_timeout_minutes}m"

            job = self.queue.enqueue(
                "docling_jobkit.orchestrators.rq.worker.docling_task",
                task_data,
                options: {
                        "do_ocr": False,                    # TODO: Enable after models are cached
                        "do_table_structure": True,
                        "include_images": False             # CRITICAL: Prevents ZIP bundling
                },
                scratch_dir=scratch_dir,
                job_timeout=job_timeout_str,  # Configurable job timeout (default 60 minutes)
                result_ttl=14400  # 4 hours - results stored in Redis for 4 hours
            )

            logger.info(f"✅ [RQ_ENQUEUE] Job enqueued: {job.id} for {filename}")
            logger.info(f"   Task ID: {task_id}")
            logger.info(f"   Presigned URL: {presigned_url[:50]}...")
            logger.info(f"   MIME type: {mime_type}")

            return job.id

        except Exception as e:
            logger.error(f"❌ [RQ_ENQUEUE] Failed to enqueue job for {filename}: {e}")
            raise

    async def poll_job_result(
        self,
        job_id: str,
        timeout: int = None,
        poll_interval_initial: int = None,
        poll_interval_max: int = None
    ) -> Tuple[str, dict]:
        """
        Poll for job completion with exponential backoff.

        Args:
            job_id: RQ job ID to poll
            timeout: Maximum time to wait in seconds (uses instance timeout if None)
            poll_interval_initial: Initial poll interval in seconds (uses instance value if None)
            poll_interval_max: Maximum poll interval in seconds (uses instance value if None)

        Returns:
            Tuple of (json_content, metadata)

        Raises:
            TimeoutError: If job doesn't complete within timeout
            Exception: If job fails
        """
        # Use instance config if parameters not provided
        if timeout is None:
            timeout = self.polling_timeout_seconds
        if poll_interval_initial is None:
            poll_interval_initial = self.poll_initial_delay
        if poll_interval_max is None:
            poll_interval_max = self.poll_max_interval

        start_time = time.time()
        interval = poll_interval_initial

        logger.info(f"⏳ [RQ_POLL] Starting poll for job: {job_id} (timeout: {timeout}s = {timeout/60:.1f} minutes)")

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
                        logger.info(f"📝 [RQ_RESULT] Result is dict - using markdown field")
                    elif isinstance(result, str):
                        # Check if result is a Redis key reference (e.g., "docling:results:...")
                        if result.startswith('docling:results:'):
                            logger.info(f"📝 [RQ_RESULT] Result is Redis key reference: {result}")
                            try:
                                # Fetch the value from Redis using the key
                                # Value could be either: S3 key path OR actual JSON content
                                redis_value = self.redis_conn.get(result)
                                if redis_value:
                                    # Handle binary data - try multiple decodings
                                    redis_value_str = None
                                    if isinstance(redis_value, bytes):
                                        # Try UTF-8 first
                                        try:
                                            redis_value_str = redis_value.decode('utf-8')
                                            logger.info(f"✅ [RQ_REDIS_FETCH] Decoded as UTF-8")
                                        except UnicodeDecodeError:
                                            # Try latin-1 (can decode any byte sequence)
                                            try:
                                                redis_value_str = redis_value.decode('latin-1')
                                                logger.info(f"✅ [RQ_REDIS_FETCH] Decoded as latin-1")
                                            except Exception as e2:
                                                logger.error(f"❌ [RQ_REDIS_FETCH] Failed all decodings: {e2}")
                                                logger.debug(f"📊 [RQ_REDIS_FETCH] First 20 bytes: {redis_value[:20]}")
                                                markdown = ""
                                                metadata = {}
                                                raise
                                    else:
                                        redis_value_str = str(redis_value)

                                    if redis_value_str:
                                        logger.info(f"✅ [RQ_REDIS_FETCH] Successfully fetched from Redis key: {result}")
                                        logger.info(f"📋 [RQ_REDIS_VALUE] Length: {len(redis_value_str)} chars, First 50: {redis_value_str[:50]}")

                                        # Check if value is an S3 key path (e.g., "docling-results/task_id/result.json")
                                        # or actual JSON content (starts with '{' or '[')
                                        if redis_value_str.startswith('docling-results/'):
                                            # This is an S3 key path stored in Redis
                                            logger.info(f"📦 [S3_KEY_FROM_REDIS] S3 key found in Redis: {redis_value_str}")
                                            markdown = redis_value_str  # Return the S3 key for caller to fetch
                                        elif redis_value_str.startswith('{') or redis_value_str.startswith('['):
                                            # This is actual JSON content
                                            logger.info(f"📄 [JSON_FROM_REDIS] Actual JSON content found in Redis")
                                            markdown = redis_value_str
                                        else:
                                            # Unknown format - log details for debugging
                                            logger.warning(f"⚠️ [RQ_REDIS_FETCH] Unknown value format: {redis_value_str[:100]}")
                                            markdown = redis_value_str
                                        metadata = {}
                                else:
                                    logger.error(f"❌ [RQ_REDIS_FETCH] Redis key {result} not found or expired")
                                    markdown = ""
                                    metadata = {}
                            except Exception as e:
                                logger.error(f"❌ [RQ_REDIS_FETCH] Failed to fetch from Redis key {result}: {e}")
                                import traceback
                                logger.error(f"📊 [RQ_REDIS_FETCH] Traceback: {traceback.format_exc()}")
                                markdown = ""
                                metadata = {}
                        else:
                            # Direct JSON content or S3 key as string
                            logger.info(f"📝 [RQ_RESULT] Result is direct string (JSON or S3 key)")
                            markdown = result
                            metadata = {}
                    else:
                        logger.warning(f"⚠️ [RQ_RESULT] Unexpected result type: {type(result)}")
                        markdown = str(result)
                        metadata = {}

                    logger.info(f"📝 [RQ_RESULT] Content length: {len(markdown)} chars")
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
        timeout_seconds: int = None
    ) -> Tuple[str, dict]:
        """
        High-level method: enqueue job, poll for result, return content.

        Args:
            presigned_url: Presigned S3 URL
            filename: Original filename
            mime_type: MIME type
            timeout_seconds: Timeout for polling (uses instance timeout if None)

        Returns:
            Tuple of (json_content, metadata)
        """
        try:
            # Use instance timeout if not provided
            if timeout_seconds is None:
                timeout_seconds = self.polling_timeout_seconds

            # Enqueue the job
            job_id = await self.enqueue_document(presigned_url, filename, mime_type)

            # Poll for result with configured timeout
            json_content, metadata = await self.poll_job_result(
                job_id,
                timeout=timeout_seconds
            )

            return json_content, metadata

        except Exception as e:
            logger.error(f"❌ [RQ_PROCESS] Error processing {filename}: {e}")
            raise
