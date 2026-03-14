from typing import List, Optional

from pydantic import BaseModel


class ChatMessageResponse(BaseModel):
    id: str
    text: str
    sender: str
    timestamp: str
    session_id: str
    used_rag: Optional[bool] = False
    used_postgres: Optional[bool] = False
    confidence_score: Optional[float] = None
    sources: Optional[list] = None
    is_message_read: Optional[bool] = False

class ChatSessionResponse(BaseModel):
    id: str
    session_uuid: Optional[str] = None  # UUID value (httpOnly cookie value)
    customer_name: Optional[str] = None
    customer_email: Optional[str] = None
    status: str
    last_message_at: str
    created_at: Optional[str] = None
    assigned_agent: Optional[str] = None
    assigned_agent_id: Optional[int] = None  # Numeric user ID for comparison (not masked)
    is_assigned_to_me: Optional[bool] = False
    feedback: Optional[str] = None
    customer_feedback: Optional[str] = None
    agent_feedback: Optional[str] = None
    chat_type: str
    is_session_read: Optional[bool] = False
    messages: List[ChatMessageResponse] = []

class ChatSessionsResponse(BaseModel):
    sessions: List[ChatSessionResponse]
    total_count: int
    page: int
    limit: int
    total_pages: int

class SendMessageRequest(BaseModel):
    text: str
    sender: str = 'agent'
    agent_id: str

class SendMessageResponse(BaseModel):
    message_id: str
    success: bool
