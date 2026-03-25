"""
Small helper for publishing extraction jobs to the dedicated Kreuzberg worker.
"""

from __future__ import annotations

from typing import Any, Dict, Optional

from shared.extraction_jobs import ExtractionJob
from shared.redis_message_queue import RedisMessageQueue


class ExtractionWorkerClient:
    """Thin wrapper around RedisMessageQueue for Kreuzberg extraction jobs."""

    def __init__(self, queue: Optional[RedisMessageQueue] = None):
        self.queue = queue or RedisMessageQueue()

    def create_job(
        self,
        *,
        document_id: str,
        worker_type: str,
        s3_key: str,
        original_filename: Optional[str] = None,
        mime_type: Optional[str] = None,
        artifact_prefix: str,
        reply_channel: str = "kreuzberg_extraction_results",
    ) -> Dict[str, Any]:
        job = ExtractionJob.new(
            document_id=document_id,
            worker_type=worker_type,
            s3_key=s3_key,
            original_filename=original_filename,
            mime_type=mime_type,
            artifact_prefix=artifact_prefix,
            reply_channel=reply_channel,
        )
        return job.to_dict()

    def publish_job(self, job: Dict[str, Any]) -> bool:
        return self.queue.publish_extract_task(job)

    def get_result(self, timeout: int = 0, queue_name: Optional[str] = None, worker_type: str = "file"):
        return self.queue.get_extract_result(timeout=timeout, queue_name=queue_name, worker_type=worker_type)
