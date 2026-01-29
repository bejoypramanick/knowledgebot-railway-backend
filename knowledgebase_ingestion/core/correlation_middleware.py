"""
Correlation ID Middleware for Knowledgebase Ingestion Service.
Ensures every request has a correlation ID for tracing across services.
"""
from fastapi import Request, Response
from starlette.middleware.base import BaseHTTPMiddleware

from .correlation_id import (
    CORRELATION_ID_HEADER,
    extract_or_generate_correlation_id,
    set_correlation_id
)
from .logging_config import get_railway_logger

logger = get_railway_logger(__name__)


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """Middleware to add correlation ID to all incoming and outgoing requests."""
    
    async def dispatch(self, request: Request, call_next):
        # Extract or generate correlation ID from incoming request
        correlation_id = extract_or_generate_correlation_id(dict(request.headers))
        
        # Set correlation ID in context for this request
        set_correlation_id(correlation_id)
        
        # Log the incoming request with correlation ID
        logger.info(f"🔍 [{correlation_id}] {request.method} {request.url.path} - Knowledgebase request received")
        
        # Process the request
        response = await call_next(request)
        
        # Add correlation ID to response headers
        response.headers[CORRELATION_ID_HEADER] = correlation_id
        
        # Log the response with correlation ID
        logger.info(f"🔍 [{correlation_id}] {request.method} {request.url.path} - Knowledgebase response sent (Status: {response.status_code})")
        
        return response
