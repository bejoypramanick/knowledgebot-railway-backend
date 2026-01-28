from pydantic import BaseModel, HttpUrl, Field, validator
from typing import Optional, List, Dict, Any
from ..utils.validation import validate_url, validate_patterns, MAX_URL_LENGTH

MAX_PAGES_LIMIT = 100
MAX_DEPTH_LIMIT = 5

class ScrapeRequest(BaseModel):
    url: str = Field(..., description="URL to scrape", min_length=1, max_length=MAX_URL_LENGTH)
    session_id: Optional[str] = Field(None, description="Session ID for SSE progress tracking")
    max_depth: Optional[int] = Field(1, ge=0, le=MAX_DEPTH_LIMIT, description="Maximum crawl depth")
    max_pages: Optional[int] = Field(10, ge=1, le=MAX_PAGES_LIMIT, description="Maximum pages to scrape")
    include_patterns: Optional[List[str]] = Field(None, description="URL patterns to include")
    exclude_patterns: Optional[List[str]] = Field(None, description="URL patterns to exclude")
    wait_for: Optional[str] = Field(None, max_length=200, description="CSS selector to wait for")
    js_code: Optional[str] = Field(None, max_length=5000, description="JavaScript to execute")
    screenshot: Optional[bool] = Field(False, description="Take screenshot of page")
    replace_existing: Optional[bool] = Field(False, description="Replace existing website if duplicate found")
    
    @validator('url')
    def validate_url_format(cls, v):
        is_valid, error = validate_url(v)
        if not is_valid:
            raise ValueError(error)
        return v
    
    @validator('include_patterns', 'exclude_patterns')
    def validate_pattern_list(cls, v):
        is_valid, error = validate_patterns(v)
        if not is_valid:
            raise ValueError(error)
        return v

class ScrapeResponse(BaseModel):
    success: bool
    message: str
    file_name: Optional[str] = None
    file_info: Optional[Dict[str, Any]] = None
    scraped_urls: Optional[List[str]] = None
    validation_warnings: Optional[List[str]] = None
