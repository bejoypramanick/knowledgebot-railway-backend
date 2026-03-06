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
        ]
        
        # Path prefixes that don't require authentication
        self.exclude_prefixes = [
            "/api/v1/gateway/chatbot/sessions/",  # Anonymous chat session creation
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
        
        # Skip authentication for excluded paths
        if self.is_excluded_path(path):
            return await call_next(request)
        
        # Skip authentication for OPTIONS requests (CORS preflight)
        if request.method == "OPTIONS":
            return await call_next(request)
        
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
        from api_gateway.routers.auth_router import get_session
        
        # Get client IP and User-Agent for security validation
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        
        # Validate session with security checks
        session_data = get_session(session_id, ip_address, user_agent, validate_security=True)
        
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

        # 🔄 STEP 2: Resolve chat session UUID to numeric ID (from httpOnly cookie)
        # Session UUID should ONLY come from httpOnly cookie, never from URL/params/body
        # This happens ONCE at API Gateway, so internal services don't need to lookup
        from api_gateway.core.session_resolver import extract_session_uuid_from_cookie, resolve_session_uuid_to_numeric_id

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
                logger.warning(f"⚠️ Could not resolve session UUID {session_uuid}")

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
