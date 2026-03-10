"""
Authentication Router (Refactored)
Handles session creation, logout, and user info with:
- Service layer separation (ProfileService, SessionService)
- Dependency injection for testability
- Enhanced security (CSRF, strict validation)
- Performance optimizations (connection pooling, write-back throttling)
"""
from fastapi import APIRouter, HTTPException, Response, Request, Depends
from pydantic import BaseModel
from typing import Optional

from api_gateway.core.firebase_auth import verify_firebase_token
from api_gateway.core.logging_config import get_railway_logger
from api_gateway.core.session_store import get_session_store
from api_gateway.core.config import get_settings
from api_gateway.services.profile_service import get_profile_service, ProfileService
from api_gateway.services.session_service import get_session_service, SessionService

logger = get_railway_logger(__name__)
router = APIRouter()


class CreateSessionRequest(BaseModel):
    """Request body for creating a session from Firebase ID token"""
    idToken: str
    context: Optional[str] = "admin"  # "admin" or "widget"


# Dependency injection helpers
def get_session_service_dep() -> SessionService:
    """Dependency for SessionService"""
    store = get_session_store()
    return get_session_service(store)


def get_profile_service_dep() -> ProfileService:
    """Dependency for ProfileService"""
    return get_profile_service()


@router.post("/auth/session")
async def create_session_endpoint(
    request: CreateSessionRequest,
    response: Response,
    req: Request,
    session_service: SessionService = Depends(get_session_service_dep),
    profile_service: ProfileService = Depends(get_profile_service_dep)
):
    """
    Create a session cookie from Firebase ID token.
    
    Flow:
    1. Verify Firebase ID token
    2. Fetch user profile (role) from configuration service
    3. Create session with security binding
    4. Set httpOnly, secure cookie
    
    Security:
    - CSRF protection via Origin validation
    - Session binding to IP and User-Agent
    - Context-aware SameSite policy
    
    Args:
        request.idToken: Firebase ID token
        request.context: "admin" (SameSite=Lax) or "widget" (SameSite=None)
    
    Returns:
        User data (uid, email, name, picture)
    """
    settings = get_settings()
    
    try:
        # CSRF Protection: Validate Origin header for state-changing requests
        origin = req.headers.get("origin")
        if origin and not _is_allowed_origin(origin, settings.allowed_origins):
            logger.warning(f"🚨 CSRF: Rejected request from origin {origin}")
            raise HTTPException(status_code=403, detail="Invalid origin")
        
        # Step 1: Verify Firebase ID token
        user_data = verify_firebase_token(request.idToken)
        if not user_data:
            raise HTTPException(status_code=401, detail="Invalid Firebase ID token")
        
        logger.info(f"✅ Firebase token verified for {user_data.get('email')}")
        
        # Step 2: Fetch user profile (role) from configuration service
        try:
            profile = await profile_service.fetch_user_profile(user_data)
            user_data.update(profile)
            logger.info(f"✅ Profile fetched: role={profile['role']}, roles={profile['roles']}")
        except Exception as e:
            logger.error(f"❌ Profile fetch failed: {e}")
            # Use fallback profile (role=user)
            user_data.update({'role': 'user', 'roles': ['user']})
        
        # Step 3: Create session with security metadata
        ip_address = req.client.host if req.client else None
        user_agent = req.headers.get("user-agent")
        
        session_id = session_service.create_session(user_data, ip_address, user_agent)
        
        # Step 4: Set cookie with context-appropriate SameSite policy
        context = request.context or "admin"
        samesite_policy = "none" if context == "widget" else "lax"
        
        response.set_cookie(
            key=settings.session_cookie_name,
            value=session_id,
            max_age=settings.session_max_age,
            httponly=True,   # XSS protection
            secure=True,     # HTTPS only (required for SameSite=None)
            samesite=samesite_policy,
            domain=settings.session_domain,
            path="/"
        )
        
        logger.info(
            f"✅ Session created for {user_data.get('email')} "
            f"(context={context}, samesite={samesite_policy})"
        )
        
        return {
            "success": True,
            "user": {
                "uid": user_data.get("uid"),
                "email": user_data.get("email"),
                "name": user_data.get("name", user_data.get("email")),
                "picture": user_data.get("picture")
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Session creation failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to create session")


@router.post("/auth/logout")
async def logout(
    request: Request,
    response: Response,
    session_service: SessionService = Depends(get_session_service_dep)
):
    """
    Logout and clear session cookie.
    
    Deletes the session from storage and clears the cookie.
    """
    settings = get_settings()
    
    try:
        # Get session ID from cookie
        session_id = request.cookies.get(settings.session_cookie_name)
        
        if session_id:
            session_service.delete_session(session_id)
        
        # Clear cookie
        response.delete_cookie(
            key=settings.session_cookie_name,
            domain=settings.session_domain,
            path="/"
        )
        
        logger.info("✅ User logged out")
        
        return {"success": True, "message": "Logged out successfully"}
        
    except Exception as e:
        logger.error(f"❌ Logout failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to logout")


@router.get("/auth/me")
async def get_current_user(
    request: Request,
    session_service: SessionService = Depends(get_session_service_dep)
):
    """
    Get current user from session cookie.
    
    Returns user data if session is valid, 401 if not authenticated.
    Validates IP and User-Agent to detect session hijacking.
    """
    settings = get_settings()
    
    try:
        # Get session ID from cookie
        session_id = request.cookies.get(settings.session_cookie_name)
        
        if not session_id:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Get session with security validation
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        
        session_data = session_service.get_session(
            session_id,
            ip_address,
            user_agent,
            validate_security=True
        )
        
        if not session_data:
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        
        return {
            "success": True,
            "user": {
                "uid": session_data["uid"],
                "email": session_data["email"],
                "name": session_data["name"],
                "picture": session_data["picture"]
            }
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Get current user failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to get user")


@router.post("/auth/refresh")
async def refresh_session(
    request: Request,
    response: Response,
    session_service: SessionService = Depends(get_session_service_dep)
):
    """
    Refresh session cookie to extend expiration.
    
    Call this periodically (e.g., every 30 minutes) to keep user logged in.
    """
    settings = get_settings()
    
    try:
        # Get session ID from cookie
        session_id = request.cookies.get(settings.session_cookie_name)
        
        if not session_id:
            raise HTTPException(status_code=401, detail="Not authenticated")
        
        # Refresh session
        success = session_service.refresh_session(session_id)
        
        if not success:
            raise HTTPException(status_code=401, detail="Invalid or expired session")
        
        # Reset cookie with new expiration
        response.set_cookie(
            key=settings.session_cookie_name,
            value=session_id,
            max_age=settings.session_max_age,
            httponly=True,
            secure=True,
            samesite="lax",
            domain=settings.session_domain,
            path="/"
        )
        
        logger.info("✅ Session refreshed")
        
        return {"success": True, "message": "Session refreshed"}
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Session refresh failed: {e}")
        raise HTTPException(status_code=500, detail="Failed to refresh session")


def _is_allowed_origin(origin: str, allowed_origins: list) -> bool:
    """
    Check if origin is in allowed list.
    
    Args:
        origin: Origin header from request
        allowed_origins: List of allowed origins
    
    Returns:
        True if allowed, False otherwise
    """
    return origin in allowed_origins
