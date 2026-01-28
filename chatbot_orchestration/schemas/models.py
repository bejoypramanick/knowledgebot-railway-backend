from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


class SearchResult(BaseModel):
    """Search result from Gemini FileSearch with comprehensive metadata."""
    # Original fields
    file_name: str
    content: str
    relevance_score: Optional[float] = None

    # Enhanced metadata fields to match frontend DocumentSource interface
    chunk_id: Optional[str] = None
    document_id: Optional[str] = None
    source: Optional[str] = None
    s3_key: Optional[str] = None
    original_filename: Optional[str] = None
    page_number: Optional[int] = None
    element_type: Optional[str] = None
    hierarchy_level: Optional[int] = None
    similarity_score: Optional[float] = None  # Alias for relevance_score
    metadata: Optional[Dict[str, Any]] = None


class ChatResponse(BaseModel):
    """Structured chat response."""
    answer: str = Field(description="The answer to the user's question")
    sources: List[SearchResult] = Field(default_factory=list, description="Sources used for the answer")
    confidence: float = Field(ge=0.0, le=1.0, description="Confidence score for the answer")
    data_sources_used: List[str] = Field(default_factory=list, description="Data sources used: rag, postgres, neon_db, internet")


class HumanReviewRequest(BaseModel):
    """Request for human review."""
    approved: bool
    feedback: Optional[str] = None
    corrected_answer: Optional[str] = None


class ChatRequest(BaseModel):
    """Chat request model."""
    message: str
    session_id: Optional[str] = None
    use_rag: bool = True
    max_results: int = 5
    system_prompt: Optional[str] = None  # Custom system prompt (will be appended to default)
    response_policy: Optional[int] = None  # 0-100: 0=flexible, 100=strict


class ChatSessionResponse(BaseModel):
    """Chat session response."""
    session_id: str
    message: str
    response: ChatResponse
    usage: Optional[Dict[str, Any]] = None
    timestamp: str


class SuggestedMessagesRequest(BaseModel):
    """Request for AI-generated suggested messages."""
    session_id: str
    conversation_history: Optional[List[Dict[str, str]]] = None  # List of {role: "user"|"assistant", content: "..."}


class SuggestedMessagesResponse(BaseModel):
    """Response with AI-generated suggested messages."""
    suggested_messages: List[str]
    usage: Optional[Dict[str, Any]] = None
