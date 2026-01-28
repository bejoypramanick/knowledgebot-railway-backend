from dataclasses import dataclass

@dataclass
class ChatSessionDeps:
    """Dependencies for chat session."""
    session_id: str
