"""
Shared message contract for the Kreuzberg extraction worker.

This module keeps the queue payload shape explicit so Python workers and the
Rust extraction service can evolve against the same schema.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class ExtractionJob:
    """Queue payload sent to the Kreuzberg extraction worker."""

    job_id: str
    document_id: str
    worker_type: str
    s3_key: str
    original_filename: Optional[str] = None
    mime_type: Optional[str] = None
    artifact_prefix: str
    reply_channel: str = "kreuzberg_extraction_results"
    created_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def new(
        cls,
        *,
        document_id: str,
        worker_type: str,
        s3_key: str,
        original_filename: Optional[str] = None,
        mime_type: Optional[str] = None,
        artifact_prefix: str,
        reply_channel: str = "kreuzberg_extraction_results",
    ) -> "ExtractionJob":
        return cls(
            job_id=str(uuid.uuid4()),
            document_id=document_id,
            worker_type=worker_type,
            s3_key=s3_key,
            original_filename=original_filename,
            mime_type=mime_type,
            artifact_prefix=artifact_prefix,
            reply_channel=reply_channel,
        )


@dataclass
class ExtractionResult:
    """Queue payload emitted by the Kreuzberg extraction worker."""

    job_id: str
    document_id: str
    worker_type: str
    status: str
    manifest_s3_key: Optional[str] = None
    error: Optional[str] = None
    completed_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
