"""Redis Queue client for docling-serve integration."""
import asyncio
import json
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
        queue_name: str = "convert",
        worker_type: str = "file",  # NEW: Identifies which worker (file or web)
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
            worker_type: Type of worker (file or web) - used for job ownership tracking
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
        self.worker_type = worker_type
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
        logger.info(f"🔌 [RQ_CLIENT] Worker type: {worker_type}")
        logger.info(f"⏱️  [RQ_CLIENT] Job timeout: {job_timeout_minutes} minutes")
        logger.info(f"⏱️  [RQ_CLIENT] Polling timeout: {polling_timeout_seconds} seconds ({polling_timeout_seconds/60:.1f} minutes)")
        logger.info(f"⏱️  [RQ_CLIENT] Poll intervals: {poll_initial_delay}s initial, {poll_max_interval}s max")

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
                        "url": presigned_url,
                        "filename": filename
                    }
                ],
                # Top-level orchestrator parameters
               
                # Pipeline options for Docling Engine
                "convert_options": {     
                        "do_ocr": True,          
                        "do_table_structure": True,
                        "do_formula_enrichment": True,
                        "do_code_enrichment": True,
                        "do_chart_extraction":True,
                        "table_structure_options": {
                            "mode":"accurate",
                            "do_cell_matching": False,
                        },
                        "include_images": False, # CRITICAL: Prevents ZIP bundling
                        "export_options": {
                            "format": "json"
                        },
                        "return_as_file": False,
                        "to_formats": ["json"]
                }
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
                scratch_dir=scratch_dir,
                job_timeout=job_timeout_str,  # Configurable job timeout (default 60 minutes)
                result_ttl=14400  # 4 hours - results stored in Redis for 4 hours
            )

            logger.info(f"✅ [RQ_ENQUEUE] Job enqueued: {job.id} for {filename}")
            logger.info(f"   Task ID: {task_id}")
            logger.info(f"   Presigned URL: {presigned_url[:50]}...")
            logger.info(f"   MIME type: {mime_type}")

            logger.info(f"✅ [RQ_ENQUEUE] Job enqueued: {job.id} for {filename}")
            logger.info(f"   Task ID: {task_id}")
            logger.info(f"   Presigned URL: {presigned_url[:50]}...")
            logger.info(f"   MIME type: {mime_type}")

            # ========================================================================

            # ========================================================================
            # STORE JOB METADATA - For worker ownership tracking
            # ========================================================================
            # Store metadata so we can verify this job belongs to this worker
            # when results come back from docling-serve
            try:
                import time
                metadata_key = f"docling:job:metadata:{task_id}"
                metadata_value = {
                    "worker_type": self.worker_type,
                    "job_id": job.id,
                    "filename": filename,
                    "enqueued_at": time.time(),
                    "mime_type": mime_type
                }

                # Store with TTL equal to job timeout + 1 hour buffer
                ttl = (self.job_timeout_minutes * 60) + 3600
                self.redis_conn.setex(
                    metadata_key,
                    ttl,
                    json.dumps(metadata_value)
                )

                logger.info(f"💾 [METADATA] Stored job metadata for task_id={task_id}")
                logger.info(f"   Key: {metadata_key}")
                logger.info(f"   Worker: {self.worker_type}")
                logger.info(f"   TTL: {ttl}s")

                # ================================================================
                # STORE REVERSE MAPPING - job_id -> task_id lookup
                # ================================================================
                # Store reverse mapping so we can verify ownership when polling
                # This allows us to go: job_id -> task_id -> metadata
                try:
                    mapping_key = f"docling:job_mapping:{job.id}"
                    self.redis_conn.setex(
                        mapping_key,
                        ttl,
                        task_id
                    )
                    logger.info(f"🔗 [JOB_MAPPING] Stored reverse mapping: {job.id} -> {task_id}")
                except Exception as mapping_err:
                    logger.warning(f"⚠️  [JOB_MAPPING] Failed to store job_id->task_id mapping: {mapping_err}")

            except Exception as metadata_err:
                logger.warning(f"⚠️  [METADATA] Failed to store metadata: {metadata_err}")
                logger.info(f"   Job will still process, but ownership tracking disabled")
            # PUB/SUB NOTIFICATION - Wake up docling-serve RQ worker immediately
            # ========================================================================
            # Per docling-jobkit spec, publish queued event to docling:updates channel
            # This prevents docling-serve from needing to poll the queue
            # Message format: {"task_id": "...", "task_type": "convert", "event": "queued"}
            try:
                pubsub_channel = "docling:updates"
                pubsub_message = {
                    "task_id": task_id,
                    "task_type": "convert",
                    "event": "queued"
                }
                
                # Publish to pub/sub channel
                self.redis_conn.publish(pubsub_channel, json.dumps(pubsub_message))
                
                logger.info(f"📢 [PUB_SUB] Published queued event: task_id={task_id}")
                logger.info(f"   Channel: {pubsub_channel}")
                logger.info(f"   Message: {json.dumps(pubsub_message)}")
            except Exception as pubsub_err:
                logger.warning(f"⚠️  [PUB_SUB] Failed to publish event: {pubsub_err}")
                logger.info(f"   Docling-serve will still process via queue polling (fallback)")

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

                    # ================================================================
                    # VERIFY JOB OWNERSHIP - Multi-worker routing check
                    # ================================================================
                    # Before processing result, verify this job belongs to this worker
                    # This prevents file worker from processing web worker jobs (and vice versa)
                    try:
                        mapping_key = f"docling:job_mapping:{job_id}"
                        task_id = self.redis_conn.get(mapping_key)

                        if task_id:
                            # Decode task_id if it's bytes
                            if isinstance(task_id, bytes):
                                task_id = task_id.decode('utf-8')

                            logger.info(f"🔐 [OWNERSHIP_VERIFY] Found task_id for job {job_id}: {task_id}")

                            # Now fetch the metadata to check worker_type
                            metadata_key = f"docling:job:metadata:{task_id}"
                            metadata_json = self.redis_conn.get(metadata_key)

                            if metadata_json:
                                # Decode metadata if it's bytes
                                if isinstance(metadata_json, bytes):
                                    metadata_json = metadata_json.decode('utf-8')

                                metadata = json.loads(metadata_json)
                                stored_worker_type = metadata.get('worker_type')

                                if stored_worker_type and stored_worker_type != self.worker_type:
                                    logger.error(f"❌ [OWNERSHIP_VERIFY] Job {job_id} does NOT belong to this worker!")
                                    logger.error(f"   Expected worker: {self.worker_type}")
                                    logger.error(f"   Stored worker:   {stored_worker_type}")
                                    logger.error(f"   Task ID: {task_id}")
                                    raise Exception(
                                        f"Job {job_id} belongs to {stored_worker_type} worker, "
                                        f"not {self.worker_type} worker. This indicates a configuration issue."
                                    )
                                else:
                                    logger.info(f"✅ [OWNERSHIP_VERIFY] Job ownership verified!")
                                    logger.info(f"   Worker: {stored_worker_type or 'unknown'}")
                                    logger.info(f"   Task ID: {task_id}")
                            else:
                                logger.warning(f"⚠️  [OWNERSHIP_VERIFY] Metadata not found for task {task_id}")
                                logger.warning(f"   Proceeding with result processing (metadata may have expired)")
                        else:
                            logger.warning(f"⚠️  [OWNERSHIP_VERIFY] No task_id mapping found for job {job_id}")
                            logger.warning(f"   Proceeding with result processing (mapping may have expired)")

                    except Exception as ownership_err:
                        # Only re-raise if it's an ownership mismatch (serious error)
                        if "does NOT belong" in str(ownership_err):
                            raise
                        # For other errors (lookup failed, etc), log and continue
                        logger.warning(f"⚠️  [OWNERSHIP_VERIFY] Failed to verify job ownership: {ownership_err}")
                        logger.warning(f"   Proceeding with result processing (ownership check skipped)")

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
                                # Value could be: Serialized ZipArchiveResult, S3 key path, or actual JSON content
                                redis_value = self.redis_conn.get(result)
                                if redis_value:
                                    logger.info(f"📦 [RQ_REDIS_FETCH] Fetched value from Redis, size: {len(redis_value)} bytes")
                                    logger.debug(f"📊 [RQ_REDIS_FETCH] First 20 bytes: {redis_value[:20]}")

                                    # First, try to detect if it's a serialized object (MessagePack or Pickle)
                                    deserialized_data = None
                                    redis_value_str = None

                                    # Try to detect serialization format
                                    if isinstance(redis_value, bytes):
                                        # Docling-serve uses MessagePack serialization, so try that FIRST
                                        # RQ may use pickle as fallback, but for docling we prioritize msgpack

                                        # Try MessagePack deserialization FIRST (docling-serve uses this)
                                        try:
                                            try:
                                                import msgpack
                                            except ImportError:
                                                logger.warning(f"⚠️ [RQ_DESERIALIZE] msgpack not installed - install with: pip install msgpack>=1.0.5")
                                                raise

                                            logger.debug(f"🔍 [RQ_DESERIALIZE] Trying MessagePack (first 4 bytes: {redis_value[:4].hex()})")
                                            # Try different msgpack configurations
                                            try:
                                                deserialized_data = msgpack.unpackb(redis_value, raw=False, strict_map_key=False)
                                            except TypeError:
                                                # Older msgpack versions don't have strict_map_key
                                                deserialized_data = msgpack.unpackb(redis_value, raw=False)

                                            logger.info(f"✅ [RQ_DESERIALIZE] Successfully deserialized as MessagePack")
                                            logger.debug(f"📊 [RQ_DESERIALIZE] Type: {type(deserialized_data)}, Keys: {list(deserialized_data.keys()) if isinstance(deserialized_data, dict) else 'N/A'}")
                                        except Exception as msgpack_err:
                                            logger.info(f"⚠️ [RQ_DESERIALIZE] MessagePack failed: {type(msgpack_err).__name__}: {str(msgpack_err)[:100]}")

                                            # Fallback to Pickle deserialization (RQ default, but less likely for docling-serve)
                                            try:
                                                import pickle
                                                deserialized_data = pickle.loads(redis_value)
                                                logger.info(f"✅ [RQ_DESERIALIZE] Successfully deserialized as Pickle")
                                                logger.debug(f"📊 [RQ_DESERIALIZE] Type: {type(deserialized_data)}")
                                            except Exception as pickle_err:
                                                logger.info(f"⚠️ [RQ_DESERIALIZE] Pickle also failed: {type(pickle_err).__name__}: {str(pickle_err)[:100]}")
                                                logger.debug(f"📊 [RQ_DESERIALIZE] First 20 bytes (hex): {redis_value[:20].hex()}")

                                        # If deserialization succeeded, check if it's a ZipArchiveResult
                                        if deserialized_data and isinstance(deserialized_data, dict):
                                            logger.info(f"📊 [RQ_DESERIALIZE] Top-level keys: {list(deserialized_data.keys())}")

                                            # The MessagePack structure from docling-serve is nested:
                                            # { "result": { "kind": "ZipArchiveResult", "content": <zip_bytes> }, ... }
                                            # Navigate to find the ZipArchiveResult at any level
                                            zip_result = None

                                            # Check top-level first
                                            if deserialized_data.get('kind') == 'ZipArchiveResult':
                                                zip_result = deserialized_data
                                            # Check inside 'result' key (docling-serve nests it here)
                                            elif isinstance(deserialized_data.get('result'), dict):
                                                inner = deserialized_data['result']
                                                logger.info(f"📊 [RQ_DESERIALIZE] result keys: {list(inner.keys())}")
                                                if inner.get('kind') == 'ZipArchiveResult':
                                                    zip_result = inner

                                            if zip_result:
                                                logger.info(f"📦 [ZIP_RESULT] Detected ZipArchiveResult object from Redis")
                                                zip_content = zip_result.get('content')
                                                if zip_content:
                                                    # content may be bytes or may need conversion
                                                    if isinstance(zip_content, str):
                                                        zip_content = zip_content.encode('latin-1')
                                                    logger.info(f"📦 [ZIP_RESULT] ZIP content size: {len(zip_content)} bytes, first 4 bytes: {zip_content[:4]}")

                                                    try:
                                                        import zipfile
                                                        import io

                                                        logger.info(f"🗜️ [ZIP_EXTRACT] Extracting JSON from ZipArchiveResult...")
                                                        with zipfile.ZipFile(io.BytesIO(zip_content)) as zip_file:
                                                            all_files = zip_file.namelist()
                                                            logger.info(f"📋 [ZIP_EXTRACT] Files in archive: {all_files}")
                                                            json_files = [f for f in all_files if f.endswith('.json')]
                                                            md_files = [f for f in all_files if f.endswith('.md')]
                                                            if json_files:
                                                                json_file = json_files[0]
                                                                logger.info(f"✅ [ZIP_EXTRACT] Found JSON file: {json_file}")
                                                                with zip_file.open(json_file) as f:
                                                                    redis_value_str = f.read().decode('utf-8')
                                                                    logger.info(f"✅ [ZIP_EXTRACT] Extracted JSON - length: {len(redis_value_str)} chars")
                                                            elif md_files:
                                                                md_file = md_files[0]
                                                                logger.info(f"✅ [ZIP_EXTRACT] Found Markdown file: {md_file}")
                                                                with zip_file.open(md_file) as f:
                                                                    redis_value_str = f.read().decode('utf-8')
                                                                    logger.info(f"✅ [ZIP_EXTRACT] Extracted Markdown - length: {len(redis_value_str)} chars")
                                                            else:
                                                                logger.error(f"❌ [ZIP_EXTRACT] No JSON or Markdown files in archive: {all_files}")
                                                                markdown = ""
                                                                metadata = {}
                                                                raise Exception(f"No extractable files in ZipArchiveResult: {all_files}")
                                                    except zipfile.BadZipFile as zip_err:
                                                        logger.error(f"❌ [ZIP_EXTRACT] Not a valid ZIP file: {zip_err}")
                                                        import traceback
                                                        logger.error(f"📊 [ZIP_EXTRACT] Traceback: {traceback.format_exc()}")
                                                        markdown = ""
                                                        metadata = {}
                                                        raise
                                                    except Exception as zip_err:
                                                        logger.error(f"❌ [ZIP_EXTRACT] Failed to extract from ZipArchiveResult: {zip_err}")
                                                        import traceback
                                                        logger.error(f"📊 [ZIP_EXTRACT] Traceback: {traceback.format_exc()}")
                                                        markdown = ""
                                                        metadata = {}
                                                        raise
                                                else:
                                                    logger.error(f"❌ [ZIP_RESULT] ZipArchiveResult has no 'content' field. Keys: {list(zip_result.keys())}")
                                            else:
                                                logger.warning(f"⚠️ [RQ_DESERIALIZE] Deserialized data is not a ZipArchiveResult. Checking all keys...")

                                        # If deserialization didn't help or didn't produce ZipArchiveResult, try text decoding
                                        if not redis_value_str:
                                            try:
                                                redis_value_str = redis_value.decode('utf-8')
                                                logger.info(f"✅ [RQ_REDIS_FETCH] Decoded as UTF-8")
                                            except UnicodeDecodeError:
                                                try:
                                                    redis_value_str = redis_value.decode('latin-1')
                                                    logger.info(f"✅ [RQ_REDIS_FETCH] Decoded as latin-1")
                                                except Exception as e2:
                                                    logger.error(f"❌ [RQ_REDIS_FETCH] Failed all decodings: {e2}")
                                                    markdown = ""
                                                    metadata = {}
                                                    raise

                                    if redis_value_str:
                                        logger.info(f"✅ [RQ_REDIS_FETCH] Successfully fetched value from Redis key: {result}")
                                        logger.info(f"📋 [RQ_REDIS_VALUE] Length: {len(redis_value_str)} chars")

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
                                            logger.warning(f"⚠️ [RQ_REDIS_FETCH] Unknown value format")
                                            logger.debug(f"   First 100 chars: {redis_value_str[:100]}")
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

                    # If the result is an S3 key path, verify it exists in Railway Storage
                    # and optionally download it if requested
                    if markdown and isinstance(markdown, str) and markdown.startswith('docling-results/'):
                        logger.info(f"📦 [S3_VERIFY] Verifying S3 object exists: {markdown}")
                        try:
                            # Check if we have S3 credentials configured
                            if self.railway_storage_url and self.railway_storage_access_key and self.railway_storage_secret_key:
                                import boto3
                                s3_client = boto3.client(
                                    's3',
                                    endpoint_url=self.railway_storage_url,
                                    aws_access_key_id=self.railway_storage_access_key,
                                    aws_secret_access_key=self.railway_storage_secret_key,
                                    region_name=self.railway_region or 'us-east-1'
                                )

                                # Verify object exists
                                try:
                                    response = s3_client.head_object(
                                        Bucket=self.railway_bucket_name,
                                        Key=markdown
                                    )
                                    file_size = response.get('ContentLength', 0)
                                    logger.info(f"✅ [S3_VERIFY] S3 object verified - exists at: {self.railway_bucket_name}/{markdown}")
                                    logger.info(f"📊 [S3_VERIFY] File size: {file_size} bytes")

                                    # Optionally log the object metadata
                                    if response.get('Metadata'):
                                        logger.debug(f"📋 [S3_VERIFY] S3 metadata: {response.get('Metadata')}")

                                except s3_client.exceptions.NoSuchKey:
                                    logger.error(f"❌ [S3_VERIFY] S3 object NOT found: {self.railway_bucket_name}/{markdown}")
                                    logger.warning(f"⚠️ [S3_VERIFY] Redis returned S3 key but object doesn't exist in bucket")
                                except s3_client.exceptions.NoSuchBucket:
                                    logger.error(f"❌ [S3_VERIFY] S3 bucket NOT found: {self.railway_bucket_name}")
                                except Exception as s3_err:
                                    logger.error(f"❌ [S3_VERIFY] Error verifying S3 object: {s3_err}")
                            else:
                                missing_creds = []
                                if not self.railway_storage_url:
                                    missing_creds.append("RAILWAY_STORAGE_URL")
                                if not self.railway_storage_access_key:
                                    missing_creds.append("RAILWAY_STORAGE_ACCESS_KEY")
                                if not self.railway_storage_secret_key:
                                    missing_creds.append("RAILWAY_STORAGE_SECRET_KEY")
                                logger.warning(f"⚠️ [S3_VERIFY] Cannot verify S3 - missing credentials: {', '.join(missing_creds)}")
                        except Exception as s3_verify_err:
                            logger.error(f"❌ [S3_VERIFY] Unexpected error during S3 verification: {s3_verify_err}")
                            import traceback
                            logger.error(f"📊 [S3_VERIFY] Traceback: {traceback.format_exc()}")

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

    async def download_from_s3(self, s3_key: str) -> str:
        """
        Download JSON content from Railway Storage S3.

        Args:
            s3_key: S3 object key (e.g., "docling-results/task_id/result.json")

        Returns:
            JSON content as string

        Raises:
            Exception: If download fails or S3 credentials are not configured
        """
        try:
            # Check if we have S3 credentials configured
            if not all([self.railway_bucket_name, self.railway_storage_url,
                       self.railway_storage_access_key, self.railway_storage_secret_key]):
                missing = []
                if not self.railway_bucket_name:
                    missing.append("RAILWAY_BUCKET_NAME")
                if not self.railway_storage_url:
                    missing.append("RAILWAY_STORAGE_URL")
                if not self.railway_storage_access_key:
                    missing.append("RAILWAY_STORAGE_ACCESS_KEY")
                if not self.railway_storage_secret_key:
                    missing.append("RAILWAY_STORAGE_SECRET_KEY")
                raise ValueError(f"S3 credentials not configured: {', '.join(missing)}")

            import boto3

            logger.info(f"📥 [S3_DOWNLOAD] Downloading from S3: {s3_key}")

            s3_client = boto3.client(
                's3',
                endpoint_url=self.railway_storage_url,
                aws_access_key_id=self.railway_storage_access_key,
                aws_secret_access_key=self.railway_storage_secret_key,
                region_name=self.railway_region or 'us-east-1'
            )

            # Download the object
            response = s3_client.get_object(
                Bucket=self.railway_bucket_name,
                Key=s3_key
            )

            content = response['Body'].read().decode('utf-8')
            file_size = response.get('ContentLength', len(content))

            logger.info(f"✅ [S3_DOWNLOAD] Successfully downloaded: {s3_key}")
            logger.info(f"📊 [S3_DOWNLOAD] File size: {file_size} bytes, Content length: {len(content)} chars")

            return content

        except Exception as e:
            logger.error(f"❌ [S3_DOWNLOAD] Failed to download {s3_key}: {e}")
            import traceback
            logger.error(f"📊 [S3_DOWNLOAD] Traceback: {traceback.format_exc()}")
            raise
