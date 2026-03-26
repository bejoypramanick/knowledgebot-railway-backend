"""
Correlation ID Middleware for FastAPI
Automatically extracts or generates correlation IDs for request tracing
"""
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from shared.correlation_id import get_correlation_id, set_correlation_id
from shared.otel_logger import set_request_id
import uuid


class CorrelationIDMiddleware(BaseHTTPMiddleware):
    """
    Middleware to handle correlation ID for distributed tracing.
    
    - Extracts correlation ID from incoming request headers (X-Correlation-ID)
    - Generates a new correlation ID if not present
    - Sets the correlation ID in the context for the request
    - Adds the correlation ID to the response headers
    """
    
    async def dispatch(self, request: Request, call_next):
        # Extract correlation ID from header or generate new one
        correlation_id = request.headers.get("X-Correlation-ID")
        
        if not correlation_id:
            correlation_id = str(uuid.uuid4())
        
        # Set correlation ID in context
        set_correlation_id(correlation_id)
        # Keep OTel logger context aligned with correlation IDs.
        set_request_id(correlation_id)
        
        # Process request
        response = await call_next(request)
        
        # Add correlation ID to response headers
        response.headers["X-Correlation-ID"] = correlation_id
        
        return response
