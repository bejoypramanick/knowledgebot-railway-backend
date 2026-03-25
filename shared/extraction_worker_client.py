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
        source_type: str,
        document_id: str,
        source_name: str,
        mime_type: str,
        presigned_url: str,
        worker_type: Optional[str] = None,
        source_url: Optional[str] = None,
        chunking_profile: str = "default",
        reply_channel: str = "kreuzberg_extraction_results",
        metadata: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, Any]:
        job = ExtractionJob.new(
            source_type=source_type,
            document_id=document_id,
            source_name=source_name,
            mime_type=mime_type,
            presigned_url=presigned_url,
            worker_type=worker_type,
            source_url=source_url,
            chunking_profile=chunking_profile,
            reply_channel=reply_channel,
            metadata=metadata,
        )
        return job.to_dict()

    def publish_job(self, job: Dict[str, Any]) -> bool:
        return self.queue.publish_extract_task(job)

    def get_result(self, timeout: int = 0):
        return self.queue.get_extract_result(timeout=timeout)
