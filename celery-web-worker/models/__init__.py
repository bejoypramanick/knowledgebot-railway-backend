"""
Models package for celery-web-worker

Contains value objects and data models
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

__all__ = [
    "CrawlConfig",
    "JobContext",
    "PageData",
    "UploadResult",
    "PageMetrics",
    "AggregateMetrics",
    "ProcessingResult",
    "FinalizeRequest",
]
