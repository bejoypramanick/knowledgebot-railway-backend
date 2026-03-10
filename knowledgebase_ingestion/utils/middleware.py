import time
import logging

from fastapi import Request

logger = logging.getLogger(__name__)

async def log_requests_middleware(request: Request, call_next):
    """Middleware to log all incoming requests with timing and status information."""
    start_time = time.time()
    request_id = f"{int(start_time * 1000000) % 1000000:06d}"
    
    # Get route pattern if available (e.g., /api/v1/knowledgebase/{action})
    route_path = request.url.path
    if hasattr(request, "scope") and "route" in request.scope:
        route = request.scope.get("route")
        if route and hasattr(route, "path"):
            route_path = f"{route.path} (matched: {request.url.path})"

    logger.info(f"📨 [{request_id}] {request.method} {route_path} - Client: {request.client.host if request.client else 'unknown'}")

    try:
        response = await call_next(request)
        duration = time.time() - start_time
        
        if response.status_code >= 400:
            logger.warning(f"↩️ [{request_id}] Response: {response.status_code} - Path: {request.url.path} - Duration: {duration:.3f}s")
        else:
            logger.info(f"↩️ [{request_id}] Response: {response.status_code} - Duration: {duration:.3f}s")

        return response

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"💥 [{request_id}] Request failed after {duration:.3f}s: {e}", exc_info=True)
        raise
