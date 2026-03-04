"""
Session-Based Authentication Middleware
Verifies session cookies (httpOnly, secure, SameSite) on all requests
Falls back to Firebase ID token verification for API clients
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
    
    Priority:
    1. Check session cookie (httpOnly, secure, SameSite)
    2. Fallback to Authorization header (for API clients)
    
    Adds user data to request.state for downstream use.
    """
    
    def __init__(self, app, exclude_paths=None):
        super().__init__(app)
        
        # Paths that don't require authentication
        self.exclude_paths = exclude_paths or [
            "/",
            "/health",
            "/docs",
            "/redoc",
            "/openapi.json",
            "/favicon.ico",
            "/auth/session",  # Session creation endpoint
            "/auth/logout",   # Logout endpoint
        ]
        
        # Also exclude any path ending with /health
        self.exclude_suffixes = ["/health"]
    
    def is_excluded_path(self, path: str) -> bool:
        """Check if path is excluded from authentication"""
        # Exact match
        if path in self.exclude_paths:
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
        
        # Try session cookie first (preferred method)
        session_id = request.cookies.get("session")
        
        if session_id:
            # Import here to avoid circular dependency
            from api_gateway.routers.auth_router import get_session
            
            session_data = get_session(session_id)
            
            if session_data:
                # Valid session found
                request.state.user = session_data
                request.state.user_uid = session_data["uid"]
                request.state.user_email = session_data["email"]
                request.state.user_name = session_data["name"]
                
                logger.debug(f"✅ Authenticated via session cookie: {session_data['email']} for {path}")
                
                # Continue to next middleware/endpoint
                response = await call_next(request)
                return response
            else:
                # Session invalid or expired
                logger.warning(f"⚠️ Invalid or expired session cookie for {path}")
                # Don't return error yet, try Authorization header fallback
        
        # Fallback to Authorization header (for API clients, mobile apps, etc.)
        auth_header = request.headers.get("Authorization")
        
        if not auth_header:
            logger.warning(f"❌ No session cookie or Authorization header for {path}")
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Authentication required. Please sign in.",
                    "error": "unauthorized"
                },
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # Check Bearer token format
        if not auth_header.startswith("Bearer "):
            logger.warning(f"❌ Invalid Authorization header format for {path}")
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Invalid Authorization header format. Expected: Bearer <token>",
                    "error": "unauthorized"
                },
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # Extract token
        token = auth_header.split(" ", 1)[1]
        
        # Verify Firebase token
        user_data = verify_firebase_token(token)
        
        if not user_data:
            logger.warning(f"❌ Invalid or expired Firebase token for {path}")
            return JSONResponse(
                status_code=401,
                content={
                    "detail": "Invalid or expired authentication token",
                    "error": "unauthorized"
                },
                headers={"WWW-Authenticate": "Bearer"}
            )
        
        # Add user data to request state
        request.state.user = user_data
        request.state.user_uid = user_data.get('uid')
        request.state.user_email = user_data.get('email')
        request.state.user_name = user_data.get('name', user_data.get('email'))
        
        logger.debug(f"✅ Authenticated via Firebase token: {user_data.get('email')} for {path}")
        
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
