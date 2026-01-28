from pydantic import BaseModel
from typing import Optional, Dict, Any, List

class HealthResponse(BaseModel):
    status: str
    services: Dict[str, str]

# Knowledgebase Models
class FileUploadResponse(BaseModel):
    message: str
    file_id: str
    filename: str

class FileMetadata(BaseModel):
    id: str
    filename: str
    display_name: str
    mime_type: str
    size_bytes: int
    create_time: str

class ListFilesResponse(BaseModel):
    files: List[FileMetadata]

# Website Scraping Models
class ScrapeRequest(BaseModel):
    url: str
    max_depth: Optional[int] = 1
    max_pages: Optional[int] = 10
    include_patterns: Optional[List[str]] = None
    exclude_patterns: Optional[List[str]] = None
    wait_for: Optional[str] = None
    js_code: Optional[str] = None
    screenshot: Optional[bool] = False
    replace_existing: Optional[bool] = False

class ScrapeResponse(BaseModel):
    success: bool
    message: str
    file_name: Optional[str] = None
    file_info: Optional[Dict[str, Any]] = None
    scraped_urls: Optional[List[str]] = None

# Chatbot Models
class ChatRequest(BaseModel):
    message: str
    session_id: Optional[str] = None
    use_rag: bool = True
    max_results: int = 5

class SearchResult(BaseModel):
    file_name: str
    content: str
    relevance_score: Optional[float] = None

class ChatResponse(BaseModel):
    answer: str
    sources: List[SearchResult] = []
    confidence: float
    data_sources_used: List[str] = []

class ChatSessionResponse(BaseModel):
    session_id: str
    message: str
    response: ChatResponse
    usage: Optional[Dict[str, Any]] = None
    timestamp: str

class SessionSummary(BaseModel):
    session_id: str
    created_at: str
    message_count: int

class ListSessionsResponse(BaseModel):
    sessions: List[SessionSummary]

class DeleteSessionResponse(BaseModel):
    message: str
    session_id: str

class ReviewRequest(BaseModel):
    approved: bool
    feedback: Optional[str] = None
    corrected_answer: Optional[str] = None

class ReviewResponse(BaseModel):
    message: str
    review_status: str

class SuggestedMessagesRequest(BaseModel):
    session_id: str
    conversation_history: Optional[List[Dict[str, str]]] = None

class SuggestedMessagesResponse(BaseModel):
    suggested_messages: List[str]
    usage: Optional[Dict[str, Any]] = None
