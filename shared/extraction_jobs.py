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
    source_type: str
    document_id: str
    source_name: str
    mime_type: str
    presigned_url: str
    reply_channel: str = "kreuzberg_extraction_results"
    chunking_profile: str = "default"
    worker_type: Optional[str] = None
    source_url: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    created_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)

    @classmethod
    def new(
        cls,
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
    ) -> "ExtractionJob":
        return cls(
            job_id=str(uuid.uuid4()),
            source_type=source_type,
            document_id=document_id,
            source_name=source_name,
            mime_type=mime_type,
            presigned_url=presigned_url,
            worker_type=worker_type,
            source_url=source_url,
            chunking_profile=chunking_profile,
            reply_channel=reply_channel,
            metadata=metadata or {},
        )


@dataclass
class ExtractionResult:
    """Queue payload emitted by the Kreuzberg extraction worker."""

    job_id: str
    document_id: str
    source_type: str
    status: str
    markdown_s3_key: Optional[str] = None
    chunks_s3_key: Optional[str] = None
    tables_s3_key: Optional[str] = None
    metadata: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None
    completed_at: str = field(default_factory=_utc_now)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)
