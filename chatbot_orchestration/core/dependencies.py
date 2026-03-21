from dataclasses import dataclass
from typing import Optional


@dataclass
class ChatSessionDeps:
    """Dependencies for chat session."""
    session_id: str  # UUID from frontend/cookie (e.g., "session_1234567890_abc123")
    session_db_id: Optional[str] = None  # Database ID (UUID string after PG18 migration, used for API calls)
