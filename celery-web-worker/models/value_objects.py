"""
Value Objects for ProcessingService

Immutable data containers for passing related data around without parameter sprawl.
Each VO represents a concept and keeps related data together.
"""
from dataclasses import dataclass
from typing import Dict, Any, Optional
from datetime import datetime


@dataclass(frozen=True)
class CrawlConfig:
    """Crawling configuration and limits"""
    max_depth: int
    max_pages: int
    max_concurrent: int
    delay_between_requests: float

    def __repr__(self) -> str:
        return f"CrawlConfig(depth={self.max_depth}, pages={self.max_pages}, concurrent={self.max_concurrent})"


@dataclass(frozen=True)
class JobContext:
    """Job-level context shared across all operations"""
    website_id: str
    root_url: str
    celery_task_id: str
    store_name: str
    user_role_id: Optional[str]

    def __repr__(self) -> str:
        return f"JobContext(website_id={self.website_id}, task_id={self.celery_task_id[:8]}...)"


@dataclass(frozen=True)
class PageData:
    """A single page being processed"""
    page_url: str
    page_html: str
    markdown: Optional[str] = None
    title: Optional[str] = None
    description: Optional[str] = None
    session_id: Optional[str] = None

    def __repr__(self) -> str:
        html_len = len(self.page_html) if self.page_html else 0
        md_len = len(self.markdown) if self.markdown else 0
        return f"PageData(url={self.page_url}, html={html_len}B, md={md_len}B, title={self.title})"


@dataclass(frozen=True)
class UploadResult:
    """Result of uploading a page to Gemini"""
    document_name: str
    file_search_store_name: str
    uploaded_at: datetime
    gemini_file_uri: Optional[str] = None
    display_name: Optional[str] = None
    confirmed: bool = True

    @property
    def file_search_metadata(self) -> Dict[str, Any]:
        """Build FileSearch metadata dict from upload result"""
        metadata = {
            "type": "file_search",
            "file_search_store_name": self.file_search_store_name,
            "document_name": self.document_name,
            "gemini_file_uri": self.gemini_file_uri,
            "uploaded_at": self.uploaded_at.isoformat()
        }
        if self.display_name:
            metadata["display_name"] = self.display_name
        return metadata

    def __repr__(self) -> str:
        return f"UploadResult(doc_id={self.document_name})"


@dataclass(frozen=True)
class PageMetrics:
    """Metrics for a single processed page"""
    file_size_bytes: int
    char_count: int
    processing_time_seconds: float

    def __repr__(self) -> str:
        return f"PageMetrics(size={self.file_size_bytes}B, chars={self.char_count}, time={self.processing_time_seconds:.2f}s)"


@dataclass(frozen=True)
class AggregateMetrics:
    """Cumulative metrics across all pages"""
    total_pages_uploaded: int
    total_size_bytes: int
    total_char_count: int
    total_time_seconds: float

    def __repr__(self) -> str:
        return f"AggregateMetrics(pages={self.total_pages_uploaded}, size={self.total_size_bytes}B, chars={self.total_char_count}, time={self.total_time_seconds:.1f}s)"


@dataclass(frozen=True)
class ProcessingResult:
    """Final result of processing a website"""
    success: bool
    website_id: str
    message: str
    page_count: int
    total_size_bytes: int
    total_char_count: int
    processing_time_seconds: float
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        """Convert to dictionary for API response"""
        result = {
            "success": self.success,
            "website_id": self.website_id,
            "message": self.message,
            "page_count": self.page_count,
            "total_size_bytes": self.total_size_bytes,
            "total_char_count": self.total_char_count,
            "processing_time_seconds": self.processing_time_seconds,
        }
        if self.error:
            result["error"] = self.error
        return result

    def __repr__(self) -> str:
        status = "✓" if self.success else "✗"
        return f"ProcessingResult({status} {self.message})"


@dataclass(frozen=True)
class ProcessingRequest:
    """Complete request to process a website - groups all orchestrator parameters"""
    website_id: str
    url: str
    crawl_config: CrawlConfig
    user_email: str = "admin"
    user_role_id: Optional[str] = None
    celery_task_id: Optional[str] = None
    replace_existing: bool = False
    options: Optional[Dict[str, Any]] = None

    def __repr__(self) -> str:
        return f"ProcessingRequest(website_id={self.website_id}, url={self.url})"


@dataclass(frozen=True)
class FinalizeRequest:
    """Request to finalize a website record"""
    website_id: str
    page_count: int
    total_size_bytes: int
    total_char_count: int
    file_search_store_name: str

    def __repr__(self) -> str:
        return f"FinalizeRequest(website_id={self.website_id}, pages={self.page_count}, size={self.total_size_bytes}B)"
