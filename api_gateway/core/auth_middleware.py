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
from shared.log_sanitizer import hash_pii
from shared.tenant_context import reset_tenant_context, set_tenant_context

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
        self.exclude_paths = (
            exclude_paths
            or [
                "/",
                "/health",
                "/docs",
                "/redoc",
                "/openapi.json",
                "/favicon.ico",
                "/auth/session",  # Session creation endpoint (receives Firebase token)
                "/auth/logout",  # Logout endpoint
                # Public chat widget endpoints (no authentication required)
                "/api/v1/gateway/chatbot/validate-chat",  # Anonymous widget bootstrap
                "/api/v1/gateway/chatbot/chat/stream",  # Anonymous chat for website visitors
                "/api/v1/gateway/widget",  # Widget HTML page for iframe embedding
                "/api/v1/gateway/configuration/widgetConfig",  # Public widget configuration for chat window
                # Customer session endpoints (anonymous customers)
                "/api/v1/gateway/configuration/admin/chat-sessions/end-customer",  # Customer ending their session
                "/api/v1/gateway/configuration/customer/sessions/set-current",  # Customer setting current session
                "/api/v1/gateway/configuration/customer/sessions/messages",  # Customer sending messages
                "/api/v1/gateway/configuration/customer/events",  # Customer SSE events
                "/api/v1/gateway/configuration/admin/chat-sessions/feedback",  # Customer feedback
                "/api/v1/gateway/configuration/admin/chat-sessions/request-agent",  # Customer requesting agent
            ]
        )

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
        is_chat_stream_path = path == "/api/v1/gateway/chatbot/chat/stream"

        # Skip authentication for OPTIONS requests (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)

        # 🔄 STEP 1: Extract session ID from httpOnly cookie for customer endpoints
        # PG18: session_id IS the UUIDv7 PK — no resolution layer needed
        is_customer_endpoint = (
            path.startswith("/api/v1/gateway/configuration/customer/")
            or path.startswith("/api/v1/gateway/chatbot/sessions/")
            or path
            in [
                "/api/v1/gateway/configuration/admin/chat-sessions/feedback",
                "/api/v1/gateway/configuration/admin/chat-sessions/request-agent",
                "/api/v1/gateway/configuration/admin/chat-sessions/end-customer",
            ]
        )

        if is_customer_endpoint:
            session_id = request.cookies.get("chatbot_session_id")
            if session_id:
                # PG18: session_id IS the database PK — store directly, no resolution needed
                request.state.session_id = session_id
                # Avoid logging raw session IDs (treat as secrets).
                logger.debug("🔄 Customer session cookie present")

        # Skip authentication for excluded paths (anonymous customers, public endpoints)
        is_excluded = self.is_excluded_path(path)
        if is_chat_stream_path and request.cookies.get("session"):
            is_excluded = False
        if is_excluded:
            logger.debug(f"✅ Path is excluded from auth: {path}")
            return await call_next(request)

        # 🔐 STEP 2: Verify Firebase authentication for protected endpoints
        # ONLY accept session cookies (no Authorization header fallback)
        session_id = request.cookies.get("session")

        if not session_id:
            logger.warning(f"❌ No session cookie for {path} (excluded: {is_excluded})")
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Authentication required. Please sign in.",
                    "error": "unauthorized",
                },
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
        session_data = session_service.get_session(
            session_id, ip_address, user_agent, validate_security=True
        )

        if not session_data:
            # Session invalid, expired, or potentially hijacked
            logger.warning(f"⚠️ Invalid or expired session cookie for {path}")
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Session expired. Please sign in again.",
                    "error": "session_expired",
                },
            )

        # Valid session found - add user data to request state
        request.state.user = session_data
        request.state.user_uid = session_data["uid"]
        request.state.user_email = session_data["email"]
        request.state.user_name = session_data["name"]
        request.state.user_role = session_data.get("role")
        request.state.user_role_id = session_data.get("active_user_role_id")
        request.state.tenant_id = session_data.get("active_tenant_id")
        request.state.tenant_slug = session_data.get("active_tenant_slug")
        request.state.is_platform_admin = session_data.get("role") == "superadmin"

        logger.debug(
            f"✅ Authenticated via session cookie: user_hash={hash_pii(session_data.get('email'))} path={path}"
        )

        # Continue to next middleware/endpoint
        tokens = set_tenant_context(
            tenant_id=session_data.get("active_tenant_id"),
            tenant_slug=session_data.get("active_tenant_slug"),
            user_role_id=session_data.get("active_user_role_id"),
            user_email=session_data.get("email"),
            is_platform_admin=session_data.get("role") == "superadmin",
        )
        try:
            response = await call_next(request)
            return response
        finally:
            reset_tenant_context(tokens)


def get_current_user(request: Request):
    """
    Dependency to get current authenticated user from request state.

    Usage in endpoints:
        @router.get("/protected")
        async def protected_endpoint(user = Depends(get_current_user)):
            return {"user_email": user.get("email")}
    """
    if not hasattr(request.state, "user"):
        raise HTTPException(status_code=401, detail="Authentication required")
    return request.state.user
