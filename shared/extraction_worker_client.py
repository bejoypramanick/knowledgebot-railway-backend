"""
Small helper for publishing extraction jobs to the dedicated Kreuzberg worker.
"""

from __future__ import annotations

from typing import Dict, Optional

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
        presigned_url: str,
        artifact_prefix: str,
        reply_channel: str = "kreuzberg_extraction_results",
    ) -> Dict[str, Any]:
        job = ExtractionJob.new(
            document_id=document_id,
            presigned_url=presigned_url,
            artifact_prefix=artifact_prefix,
            reply_channel=reply_channel,
        )
        return job.to_dict()

    def publish_job(self, job: Dict[str, Any]) -> bool:
        return self.queue.publish_extract_task(job)

    def get_result(self, timeout: int = 0):
        return self.queue.get_extract_result(timeout=timeout)
