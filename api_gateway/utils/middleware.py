import time

from fastapi import Request

from shared.otel_logger import get_otel_logger
from shared.correlation_id import set_correlation_id, get_correlation_id

logger = get_otel_logger(__name__, "api-gateway")

async def log_requests_middleware(request: Request, call_next):
    """Middleware to log all incoming requests with timing and status information."""
    start_time = time.time()
    # Prefer distributed correlation id across services.
    corr_id = request.headers.get("X-Correlation-ID") or get_correlation_id()
    set_correlation_id(corr_id)
    from shared.otel_logger import set_request_id, set_admin_context
    set_request_id(corr_id)
    
    # Get route pattern if available (e.g., /api/v1/gateway/auth/{action})
    route_path = request.url.path
    if hasattr(request, "scope") and "route" in request.scope:
        route = request.scope.get("route")
        if route and hasattr(route, "path"):
            route_path = f"{route.path} (matched: {request.url.path})"

    # Avoid logging full headers (often includes PII/secrets). Log only minimal routing info.
    client = request.client.host if request.client else "unknown"
    logger.info(f"📨 {request.method} {route_path} client={client}")

    try:
        # If auth middleware already populated request.state.user_email, attach admin context
        # early so downstream logs in this request get consistent user_hash and role.
        if hasattr(request.state, "user_email"):
            user_email = getattr(request.state, "user_email", None)
            user_role = request.state.user.get("role", "user") if hasattr(request.state, "user") else "user"
            if user_email:
                set_admin_context(corr_id, user_email, user_role)

        response = await call_next(request)
        
        duration = time.time() - start_time
        # Always return correlation id for clients and downstream hops.
        response.headers["X-Correlation-ID"] = corr_id
        
        if response.status_code >= 400:
            logger.warning(f"↩️ Response={response.status_code} path={request.url.path} dur_s={duration:.3f}")
            if response.status_code == 404:
                # Don't log 404 for static assets like favicon.ico
                if not request.url.path.endswith(('.ico', '.png', '.jpg', '.css', '.js')):
                    logger.error(f"❌ 404 DETECTED on path: {request.url.path}")
        else:
            logger.info(f"↩️ Response={response.status_code} dur_s={duration:.3f}")

        return response

    except Exception as e:
        duration = time.time() - start_time
        logger.error(f"💥 Request failed dur_s={duration:.3f}: {e}", exc_info=True)
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
