"""
Session-Based Authentication Middleware
Verifies session cookies (httpOnly, secure, SameSite) on all requests
ONLY accepts session cookies - no Authorization header fallback for security
API Gateway forwards user info to internal services via headers
"""
from fastapi import Request, HTTPException
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

from api_gateway.core.firebase_auth import verify_firebase_token
from api_gateway.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)


class SessionAuthMiddleware(BaseHTTPMiddleware):
    """
    Session-Based Authentication Middleware
    
    Security Model:
    - ONLY accepts httpOnly session cookies from external requests
    - NO Authorization header fallback (prevents token theft attacks)
    - API Gateway extracts user info from session
    - API Gateway forwards user info to internal services via headers
    
    Internal services trust headers from API Gateway (private network).
    """
    
    def __init__(self, app, exclude_paths=None):
        super().__init__(app)
        
        # Paths that don't require authentication
        # These are public endpoints accessible without session cookies
        self.exclude_paths = exclude_paths or [
            "/",
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/favicon.ico",
            "/auth/session",  # Session creation endpoint (receives Firebase token)
            "/auth/logout",   # Logout endpoint
            # Public chat widget endpoints (no authentication required)
            "/api/v1/gateway/chatbot/chat/stream",  # Anonymous chat for website visitors
            "/api/v1/gateway/widget",  # Widget HTML page for iframe embedding
            "/api/v1/gateway/configuration/data/security-settings",  # Public security settings for chat window
            "/api/v1/gateway/configuration/widgetConfig",  # Public widget configuration for chat window
            # Customer session endpoints (anonymous customers)
            "/api/v1/gateway/configuration/admin/chat-sessions/end-customer",  # Customer ending their session
            "/api/v1/gateway/configuration/customer/sessions/set-current",  # Customer setting current session
            "/api/v1/gateway/configuration/customer/sessions/messages",  # Customer sending messages
            "/api/v1/gateway/configuration/customer/events",  # Customer SSE events
            "/api/v1/gateway/configuration/admin/chat-sessions/feedback",  # Customer feedback
            "/api/v1/gateway/configuration/admin/chat-sessions/request-agent",  # Customer requesting agent
            "/api/v1/gateway/configuration/users/unique-id",  # Get/create user ID by email (used during agent initialization)
        ]

        # Path prefixes that don't require authentication
        self.exclude_prefixes = [
            "/api/v1/gateway/chatbot/sessions/",  # Anonymous chat session creation
            "/api/v1/gateway/configuration/customer/",  # All customer-facing endpoints
        ]
        
        # Also exclude any path ending with /health
        self.exclude_suffixes = ["/health"]
    
    def is_excluded_path(self, path: str) -> bool:
        """Check if path is excluded from authentication"""
        # Exact match
        if path in self.exclude_paths:
            return True
        
        # Prefix match
        for prefix in self.exclude_prefixes:
            if path.startswith(prefix):
                return True
        
        # Suffix match
        for suffix in self.exclude_suffixes:
            if path.endswith(suffix):
                return True
        
        return False
    
    async def dispatch(self, request: Request, call_next):
        """Process request and verify authentication"""
        path = request.url.path

        # Skip authentication for OPTIONS requests (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)

        # 🔄 STEP 1: Extract chat session UUID from httpOnly cookie ONLY for customer endpoints
        # UUID never appears in URL, params, or request body
        # After /set-current is called, UUID is in httpOnly cookie for all requests
        # ONLY resolve for customer-facing endpoints (admin endpoints don't need session UUID resolution)
        from api_gateway.core.session_resolver import extract_session_uuid_from_cookie, resolve_session_uuid_to_numeric_id

        # Only attempt session UUID resolution for customer-facing endpoints
        # Admin endpoints authenticate via Firebase, not customer session UUID
        # Also include customer-used endpoints under /admin/ path (feedback, request-agent, end-customer)
        is_customer_endpoint = path.startswith('/api/v1/gateway/configuration/customer/') or \
                               path.startswith('/api/v1/gateway/chatbot/sessions/') or \
                               path in [
                                   '/api/v1/gateway/configuration/admin/chat-sessions/feedback',
                                   '/api/v1/gateway/configuration/admin/chat-sessions/request-agent',
                                   '/api/v1/gateway/configuration/admin/chat-sessions/end-customer',
                               ]

        if is_customer_endpoint:
            session_uuid = extract_session_uuid_from_cookie(request)

            if session_uuid:
                # Resolve UUID to numeric ID
                numeric_session_id = await resolve_session_uuid_to_numeric_id(session_uuid)
                if numeric_session_id:
                    # Store both UUID and numeric ID in request state for internal services to use
                    request.state.session_uuid = session_uuid
                    request.state.session_numeric_id = numeric_session_id
                    logger.debug(f"🔄 Resolved session UUID {session_uuid} → numeric ID {numeric_session_id}")
                else:
                    logger.debug(f"⚠️ Could not resolve session UUID {session_uuid} to numeric ID")

        # Skip authentication for excluded paths (anonymous customers, public endpoints)
        if self.is_excluded_path(path):
            return await call_next(request)

        # 🔐 STEP 2: Verify Firebase authentication for protected endpoints
        # ONLY accept session cookies (no Authorization header fallback)
        session_id = request.cookies.get("session")

        if not session_id:
            logger.warning(f"❌ No session cookie for {path}")
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Authentication required. Please sign in.",
                    "error": "unauthorized"
                }
            )

        # Import here to avoid circular dependency
        from api_gateway.core.session_store import get_session_store
        from api_gateway.services.session_service import get_session_service

        # Get client IP and User-Agent for security validation
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")

        # Get session service
        session_store = get_session_store()
        session_service = get_session_service(session_store)

        # Validate session with security checks
        session_data = session_service.get_session(session_id, ip_address, user_agent, validate_security=True)

        if not session_data:
            # Session invalid, expired, or potentially hijacked
            logger.warning(f"⚠️ Invalid or expired session cookie for {path}")
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Session expired. Please sign in again.",
                    "error": "session_expired"
                }
            )

        # Valid session found - add user data to request state
        request.state.user = session_data
        request.state.user_uid = session_data["uid"]
        request.state.user_email = session_data["email"]
        request.state.user_name = session_data["name"]

        logger.debug(f"✅ Authenticated via session cookie: {session_data['email']} for {path}")

        # Continue to next middleware/endpoint
        response = await call_next(request)

        return response


def get_current_user(request: Request):
    """
    Dependency to get current authenticated user from request state.
    
    Usage in endpoints:
        @router.get("/protected")
        async def protected_endpoint(user = Depends(get_current_user)):
            return {"user_email": user.get("email")}
    """
    if not hasattr(request.state, 'user'):
        raise HTTPException(
            status_code=401,
            detail="Authentication required"
        )
    return request.state.user
