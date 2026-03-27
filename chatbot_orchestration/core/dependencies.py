from dataclasses import dataclass


@dataclass
class ChatSessionDeps:
    """Dependencies for chat session.

    PG18: session_id IS the database UUIDv7 primary key.
    No more separate session_db_id — the UUID is both the identifier and PK.
    """
    session_id: str  # PG18 UUIDv7 database primary key (e.g., "019535a0-1234-7abc-8def-0123456789ab")
