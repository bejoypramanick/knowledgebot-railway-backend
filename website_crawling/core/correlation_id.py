"""
Correlation ID utilities for request tracing across services.
"""
import uuid
from typing import Optional
from contextvars import ContextVar

# Context variable to store correlation ID throughout the request lifecycle
correlation_id_context: ContextVar[Optional[str]] = ContextVar('correlation_id', default=None)

# Standard header name for correlation IDs
CORRELATION_ID_HEADER = "X-Correlation-ID"


def generate_correlation_id() -> str:
    """Generate a new unique correlation ID."""
    return str(uuid.uuid4())


def get_correlation_id() -> Optional[str]:
    """Get the current correlation ID from context."""
    return correlation_id_context.get()


def set_correlation_id(correlation_id: str) -> None:
    """Set the correlation ID in the current context."""
    correlation_id_context.set(correlation_id)


def extract_or_generate_correlation_id(headers: dict) -> str:
    """Extract correlation ID from headers or generate a new one."""
    correlation_id = headers.get(CORRELATION_ID_HEADER.lower())
    if not correlation_id:
        correlation_id = generate_correlation_id()
    return correlation_id


def add_correlation_id_headers(headers: dict, correlation_id: str) -> dict:
    """Add correlation ID to headers dictionary."""
    headers[CORRELATION_ID_HEADER] = correlation_id
    return headers
