"""
Models package for celery-web-worker

Contains value objects, data models, and cancellation handling
"""
from .value_objects import (
    CrawlConfig,
    JobContext,
    PageData,
    UploadResult,
    PageMetrics,
    AggregateMetrics,
    ProcessingResult,
    FinalizeRequest,
)

from .cancellation import (
    CancellationToken,
    CancellationCheckpoint,
    CancellationException,
)

__all__ = [
    # Value Objects
    "CrawlConfig",
    "JobContext",
    "PageData",
    "UploadResult",
    "PageMetrics",
    "AggregateMetrics",
    "ProcessingResult",
    "FinalizeRequest",
    # Cancellation
    "CancellationToken",
    "CancellationCheckpoint",
    "CancellationException",
]
