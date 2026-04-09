"""
Authentication Router (Refactored)
Handles session creation, logout, and user info with:
- Service layer separation (ProfileService, SessionService)
- Dependency injection for testability
- Enhanced security (CSRF, strict validation)
- Performance optimizations (connection pooling, write-back throttling)
- OpenTelemetry tracing for complete request flow
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
from shared.tracing_decorator import trace_router

logger = get_railway_logger(__name__)
router = APIRouter()


class CreateSessionRequest(BaseModel):
    """Request body for creating a session from Firebase ID token"""
    idToken: str
    context: Optional[str] = "admin"  # "admin" or "widget"


class SwitchTenantRequest(BaseModel):
    """Request body for switching the active tenant inside an existing session."""
    tenant_id: Optional[str] = None
    tenant_slug: Optional[str] = None


# Dependency injection helpers
def get_session_service_dep() -> SessionService:
    """Dependency for SessionService"""
    store = get_session_store()
    return get_session_service(store)


def get_profile_service_dep() -> ProfileService:
    """Dependency for ProfileService"""
    return get_profile_service()


@router.post("/auth/session")
@trace_router(span_name="POST /auth/session")
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
    import time
    start_time = time.time()
    logger.info("[ENTRY] POST /auth/session endpoint")
    logger.info(f"[PARAM] context={request.context}")
    
    settings = get_settings()
    
    try:
        # CSRF Protection: Validate Origin header for state-changing requests
        logger.info("[FLOW] Step 1: CSRF validation")
        origin = req.headers.get("origin")
        logger.info(f"[PARAM] origin={origin}")
        
        if origin and not _is_allowed_origin(origin, settings.allowed_origins):
            logger.warning(f"[SECURITY] CSRF: Rejected request from origin {origin}")
            raise HTTPException(status_code=403, detail="Invalid origin")
        logger.info("[RESULT] CSRF validation passed")
        
        # Step 1: Verify Firebase ID token
        logger.info("[FLOW] Step 2: Firebase token verification")
        user_data = verify_firebase_token(request.idToken)
        if not user_data:
            logger.error("[ERROR] Firebase token verification failed")
            raise HTTPException(status_code=401, detail="Invalid Firebase ID token")
        
        logger.info(f"[RESULT] Firebase token verified for {user_data.get('email')}")
        
        # Step 2: Fetch user profile (role) from configuration service
        logger.info("[FLOW] Step 3: Fetch user profile from configuration service")
        try:
            preferred_tenant_id = req.headers.get("X-Tenant-ID")
            preferred_tenant_slug = req.headers.get("X-Tenant-Slug")
            profile = await profile_service.fetch_user_profile(
                user_data,
                preferred_tenant_id=preferred_tenant_id,
                preferred_tenant_slug=preferred_tenant_slug,
                use_cache=False,
            )
            user_data.update(profile)
            logger.info(
                f"[RESULT] Profile fetched: role={profile.get('role')}, roles={profile.get('roles')}"
            )
        except Exception as e:
            logger.error(f"[WARNING] Profile fetch failed: {e}")
            # Use fallback profile (role=user)
            user_data.update({'role': 'user', 'roles': ['user']})
            logger.info("[RESULT] Using fallback profile (role=user)")
        
        # Step 3: Create session with security metadata
        logger.info("[FLOW] Step 4: Create session with security metadata")
        ip_address = req.client.host if req.client else None
        user_agent = req.headers.get("user-agent")
        logger.info(f"[PARAM] ip_address={ip_address}, user_agent={user_agent}")
        
        session_id = session_service.create_session(user_data, ip_address, user_agent)
        logger.info(f"[RESULT] Session created: {session_id}")
        
        # Step 4: Set cookie with context-appropriate SameSite policy
        logger.info("[FLOW] Step 5: Set session cookie")
        context = request.context or "admin"
        samesite_policy = "none" if context == "widget" else "lax"
        logger.info(f"[PARAM] samesite_policy={samesite_policy}")
        
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
        
        elapsed_time = time.time() - start_time
        logger.info(f"[EXIT] POST /auth/session - Success (elapsed: {elapsed_time:.3f}s)")
        logger.info(f"[RETURN] User: {user_data.get('email')}, Role: {user_data.get('role')}")
        
        return {
            "success": True,
            "user": {
                "uid": user_data.get("uid"),
                "email": user_data.get("email"),
                "name": user_data.get("name", user_data.get("email")),
                "picture": user_data.get("picture"),
            },
            "tenant": {
                "tenant_id": user_data.get("tenant_id"),
                "tenant_slug": user_data.get("tenant_slug"),
                "tenant_name": user_data.get("tenant_name"),
                "active_user_role_id": user_data.get("active_user_role_id"),
            },
            "tenant_memberships": user_data.get("tenant_memberships", []),
        }
        
    except HTTPException:
        elapsed_time = time.time() - start_time
        logger.error(f"[EXIT] POST /auth/session - HTTPException (elapsed: {elapsed_time:.3f}s)")
        raise
    except Exception as e:
        elapsed_time = time.time() - start_time
        logger.error(f"[EXIT] POST /auth/session - Error (elapsed: {elapsed_time:.3f}s)")
        logger.error(f"[ERROR] Exception type: {type(e).__name__}, Message: {str(e)}")
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
            },
            "tenant": {
                "tenant_id": session_data.get("active_tenant_id"),
                "tenant_slug": session_data.get("active_tenant_slug"),
                "tenant_name": session_data.get("active_tenant_name"),
                "active_user_role_id": session_data.get("active_user_role_id"),
            },
            "tenant_memberships": session_data.get("tenant_memberships", []),
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


@router.post("/auth/switch-tenant")
async def switch_tenant(
    body: SwitchTenantRequest,
    request: Request,
    session_service: SessionService = Depends(get_session_service_dep),
):
    """Switch the active tenant on an existing authenticated session."""
    settings = get_settings()

    session_id = request.cookies.get(settings.session_cookie_name)
    if not session_id:
        raise HTTPException(status_code=401, detail="Not authenticated")

    session_data = session_service.get_session(
        session_id,
        request.client.host if request.client else None,
        request.headers.get("user-agent"),
        validate_security=True,
    )
    if not session_data:
        raise HTTPException(status_code=401, detail="Invalid or expired session")

    memberships = session_data.get("tenant_memberships", [])
    selected_membership = None

    for membership in memberships:
        if body.tenant_id and membership.get("tenant_id") == body.tenant_id:
            selected_membership = membership
            break
        if body.tenant_slug and membership.get("tenant_slug") == body.tenant_slug:
            selected_membership = membership
            break

    if not selected_membership:
        raise HTTPException(status_code=404, detail="Tenant membership not found")

    updated_session = session_service.update_session_fields(
        session_id,
        {
            "role": selected_membership.get("primary_role", "user"),
            "roles": selected_membership.get("roles", ["user"]),
            "active_tenant_id": selected_membership.get("tenant_id"),
            "active_tenant_slug": selected_membership.get("tenant_slug"),
            "active_tenant_name": selected_membership.get("tenant_name"),
            "active_user_role_id": selected_membership.get("active_user_role_id"),
        },
    )
    if not updated_session:
        raise HTTPException(status_code=404, detail="Session not found")

    return {
        "success": True,
        "tenant": {
            "tenant_id": updated_session.get("active_tenant_id"),
            "tenant_slug": updated_session.get("active_tenant_slug"),
            "tenant_name": updated_session.get("active_tenant_name"),
            "active_user_role_id": updated_session.get("active_user_role_id"),
        },
        "roles": updated_session.get("roles", ["user"]),
        "role": updated_session.get("role", "user"),
    }


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
