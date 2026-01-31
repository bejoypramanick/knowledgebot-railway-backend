import uuid
from contextvars import ContextVar
from typing import Optional

# Context variable to store the correlation ID for the current task/request
correlation_id_ctx_var: ContextVar[Optional[str]] = ContextVar("correlation_id", default=None)

def get_correlation_id() -> str:
    """
    Returns the current correlation ID or generates a new one if not set.
    """
    cid = correlation_id_ctx_var.get()
    if not cid:
        cid = str(uuid.uuid4())
        correlation_id_ctx_var.set(cid)
    return cid

def set_correlation_id(cid: str) -> None:
    """
    Sets the correlation ID for the current context.
    """
    correlation_id_ctx_var.set(cid)

def add_correlation_id_headers(headers: dict, cid: Optional[str] = None) -> dict:
    """
    Adds the correlation ID to the headers for outgoing requests.
    """
    if not cid:
        cid = get_correlation_id()
    headers["X-Correlation-ID"] = cid
    return headers
