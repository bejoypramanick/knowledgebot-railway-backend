from dataclasses import dataclass
from typing import Optional


@dataclass
class ChatSessionDeps:
    """Dependencies for chat session."""
    session_id: str  # UUID from frontend/cookie (e.g., "session_1234567890_abc123")
    numeric_session_id: Optional[int] = None  # Numeric ID from database (used for API calls)
