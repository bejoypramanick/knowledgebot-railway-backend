import time

from fastapi import Request

from shared.otel_logger import get_otel_logger

logger = get_otel_logger(__name__, "api-gateway")

async def log_requests_middleware(request: Request, call_next):
    """Middleware to log all incoming requests with timing and status information."""
    start_time = time.time()
    request_id = f"{int(start_time * 1000000) % 1000000:06d}"
    
    # Get route pattern if available (e.g., /api/v1/gateway/auth/{action})
    route_path = request.url.path
    if hasattr(request, "scope") and "route" in request.scope:
        route = request.scope.get("route")
        if route and hasattr(route, "path"):
            route_path = f"{route.path} (matched: {request.url.path})"

    logger.info(f"📨 [{request_id}] {request.method} {route_path} - Client: {request.client.host if request.client else 'unknown'}")

    safe_headers = {k: v for k, v in request.headers.items()
                   if k.lower() not in ['authorization', 'x-api-key', 'cookie']}
    if safe_headers:
        logger.debug(f"📋 [{request_id}] Headers: {dict(safe_headers)}")

    try:
        response = await call_next(request)
        duration = time.time() - start_time
        
        if response.status_code >= 400:
            logger.warning(f"↩️ [{request_id}] Response: {response.status_code} - Path: {request.url.path} - Total time: {duration:.3f}s")
            if response.status_code == 404:
                # Don't log 404 for static assets like favicon.ico
                if not request.url.path.endswith(('.ico', '.png', '.jpg', '.css', '.js')):
                    logger.error(f"❌ 404 DETECTED on path: {request.url.path}")
        else:
            logger.info(f"↩️ [{request_id}] Response: {response.status_code} - Total time: {duration:.3f}s")

        return response

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"💥 [{request_id}] Request failed after {duration:.3f}s: {e}")
        raise

async def add_security_headers_middleware(request: Request, call_next):
    """Add security headers with targeted COOP policy based on endpoint type."""
    response = await call_next(request)

    # Targeted COOP policy:
    # - Auth endpoints: allow popups (Firebase auth, OAuth, etc.)
    # - Other endpoints: strict same-origin
    path = request.url.path
    auth_endpoints = ['/auth/', '/login', '/session', '/verify']

    is_auth_endpoint = any(path.startswith(ep) for ep in auth_endpoints)

    if is_auth_endpoint:
        # Allow popups for authentication flows
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin-allow-popups"
        response.headers["Cross-Origin-Embedder-Policy"] = "unsafe-none"
    else:
        # Strict policy for non-auth endpoints
        response.headers["Cross-Origin-Opener-Policy"] = "same-origin"
        response.headers["Cross-Origin-Embedder-Policy"] = "require-corp"

    return response
