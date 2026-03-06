"""
Authentication Router
Handles session creation, logout, and user info with httpOnly cookies
Sessions stored in Redis (or in-memory fallback)
User data remains in Postgres database
"""
from fastapi import APIRouter, HTTPException, Response, Request
from pydantic import BaseModel
import secrets
import time
from typing import Optional, Dict, Any
import os

from api_gateway.core.firebase_auth import verify_firebase_token
from api_gateway.core.logging_config import get_railway_logger
from api_gateway.core.session_store import get_session_store

logger = get_railway_logger(__name__)
router = APIRouter()

# Session configuration
SESSION_COOKIE_NAME = "session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days in seconds
SESSION_DOMAIN = ".globistaan.com"  # Works for all *.globistaan.com subdomains


class CreateSessionRequest(BaseModel):
    """Request body for creating a session from Firebase ID token"""
    idToken: str
    context: Optional[str] = "admin"  # "admin" or "widget" - determines cookie SameSite policy


def get_session(session_id: str, ip_address: str = None, user_agent: str = None, 
                validate_security: bool = True) -> Optional[Dict[str, Any]]:
    """
    Get session data by session ID with security validation
    
    Args:
        session_id: Session ID from cookie
        ip_address: Client IP address for validation
        user_agent: Client User-Agent for validation
        validate_security: Whether to validate IP and User-Agent (default: True)
    
    Returns:
        Session data if valid, None if invalid/expired/hijacked
    """
    # Get session store
    store = get_session_store()
    
    # Get session data from Redis/memory
    session_data = store.get(session_id)
    
    if not session_data:
        return None
    
    # Check if session expired (Redis handles this automatically, but check for in-memory)
    if session_data.get("expires_at") and session_data["expires_at"] < int(time.time()):
        # Session expired, delete it
        store.delete(session_id)
        logger.info(f"⏰ Session expired for {session_data.get('email')}")
        return None
    
    # Security validation (detect session hijacking)
    if validate_security:
        # Check IP address match (with flexibility for mobile networks and Railway internal IPs)
        if ip_address and session_data.get("ip_address"):
            if ip_address != session_data["ip_address"]:
                # Check if both IPs are Railway internal IPs (100.64.0.0/10)
                is_railway_internal = (
                    ip_address.startswith("100.64.") and 
                    session_data["ip_address"].startswith("100.64.")
                )
                
                if is_railway_internal:
                    # Railway internal IPs can change due to load balancing - just log, don't block
                    logger.debug(
                        f"ℹ️ Railway internal IP change for {session_data.get('email')}: "
                        f"{session_data['ip_address']} → {ip_address} (allowed)"
                    )
                else:
                    # External IP mismatch - potential hijacking
                    logger.warning(
                        f"🚨 IP address mismatch for {session_data.get('email')}: "
                        f"expected {session_data['ip_address']}, got {ip_address}"
                    )
                    # For now, just log warning (don't invalidate)
                    # In production, you might want to invalidate or require re-auth
                    # Uncomment below to enforce strict IP binding:
                    # store.delete(session_id)
                    # return None
        
        # Check User-Agent match (detect browser/device change)
        if user_agent and session_data.get("user_agent"):
            if user_agent != session_data["user_agent"]:
                logger.warning(
                    f"🚨 User-Agent mismatch for {session_data.get('email')}: "
                    f"session created with different browser/device"
                )
                # For now, just log warning
                # Uncomment below to enforce strict User-Agent binding:
                # store.delete(session_id)
                # return None
    
    # Update request tracking
    session_data["request_count"] = session_data.get("request_count", 0) + 1
    session_data["last_request_time"] = int(time.time())
    
    # Update session in store (for request tracking)
    store.create(session_id, session_data, SESSION_MAX_AGE)
    
    # Detect unusual activity (too many requests)
    if session_data["request_count"] > 10000:  # Adjust threshold as needed
        logger.warning(
            f"🚨 Unusual activity detected for {session_data.get('email')}: "
            f"{session_data['request_count']} requests"
        )
    
    return session_data


def create_session(user_data: Dict[str, Any], ip_address: str = None, user_agent: str = None) -> str:
    """Create a new session and return session ID"""
    # Generate secure random session ID
    session_id = secrets.token_urlsafe(32)
    
    # Get session store
    store = get_session_store()
    
    # Prepare session data with security metadata
    session_data = {
        "uid": user_data.get("uid"),
        "email": user_data.get("email"),
        "name": user_data.get("name", user_data.get("email")),
        "picture": user_data.get("picture"),
        "role": user_data.get("role", "user"),  # Store user role
        "roles": user_data.get("roles", ["user"]),  # Store all roles
        "created_at": int(time.time()),
        "expires_at": int(time.time()) + SESSION_MAX_AGE,
        # Security: Bind session to IP and User Agent
        "ip_address": ip_address,
        "user_agent": user_agent,
        "request_count": 0,
        "last_request_time": int(time.time())
    }
    
    # Store session in Redis/memory with TTL
    store.create(session_id, session_data, SESSION_MAX_AGE)
    
    logger.info(f"✅ Session created for user {user_data.get('email')} (role={user_data.get('role')}) from IP {ip_address} (expires in {SESSION_MAX_AGE}s)")
    
    return session_id


def delete_session(session_id: str) -> bool:
    """Delete a session"""
    store = get_session_store()
    result = store.delete(session_id)
    
    if result:
        logger.info(f"✅ Session {session_id[:8]}... deleted")
    
    return result


@router.post("/auth/session")
async def create_session_endpoint(
    request: CreateSessionRequest,
    response: Response,
    req: Request
):
    """
    Create a session cookie from Firebase ID token.
    
    Flow:
    1. Frontend gets Firebase ID token after Google sign-in
    2. Frontend calls this endpoint with the token and context
    3. Backend verifies token with Firebase Admin SDK
    4. Backend fetches user role from database
    5. Backend creates session and sets httpOnly, secure cookie
    6. Frontend uses cookie for all subsequent requests (automatic)
    
    Context-aware cookie configuration:
    - Admin/Agent screens: SameSite=Lax (same-site only, more secure)
    - Chat widget (iframe): SameSite=None (cross-site, required for iframes)
    
    Security:
    - Binds session to IP address and User-Agent
    - Detects session hijacking attempts
    
    Args:
        request.idToken: Firebase ID token
        request.context: "admin" (default) or "widget"
    
    Returns:
        User data (uid, email, name, picture, role)
    """
    try:
        logger.info(f"🔐 [SESSION_CREATE] Received session creation request")
        logger.info(f"🔐 [SESSION_CREATE] Context: {request.context}")
        logger.info(f"🔐 [SESSION_CREATE] Origin: {req.headers.get('origin')}")
        logger.info(f"🔐 [SESSION_CREATE] Referer: {req.headers.get('referer')}")
        
        # Verify Firebase ID token
        user_data = verify_firebase_token(request.idToken)
        
        if not user_data:
            logger.warning("❌ Invalid Firebase ID token provided")
            raise HTTPException(
                status_code=401,
                detail="Invalid Firebase ID token"
            )
        
        logger.info(f"✅ [SESSION_CREATE] Firebase token verified for user: {user_data.get('email')}")
        
        # Fetch user role from database via configuration service
        try:
            import httpx
            from api_gateway.core.config import get_settings
            
            settings = get_settings()
            config_service_url = settings.configuration_service_url
            role_endpoint = f"{config_service_url}/api/v1/configuration/admin/users/role"
            
            logger.info(f"🔍 [SESSION_CREATE] Fetching role from: {role_endpoint}")
            logger.info(f"🔍 [SESSION_CREATE] Email: {user_data.get('email')}")
            
            async with httpx.AsyncClient(timeout=5.0) as client:
                role_response = await client.get(
                    role_endpoint,
                    params={"email": user_data.get('email')}
                )
                
                logger.info(f"🔍 [SESSION_CREATE] Role endpoint response status: {role_response.status_code}")
                logger.info(f"🔍 [SESSION_CREATE] Role endpoint response body: {role_response.text}")
                
                if role_response.status_code == 200:
                    role_result = role_response.json()
                    roles = role_result.get('roles', [])
                    # Determine primary role: admin > human_agent > user
                    if 'admin' in roles:
                        user_role = 'admin'
                    elif 'human_agent' in roles:
                        user_role = 'human_agent'
                    else:
                        user_role = 'user'
                    user_data['role'] = user_role
                    user_data['roles'] = roles
                    logger.info(f"✅ [SESSION_CREATE] User role fetched: {user_role} (all roles: {roles})")
                else:
                    logger.warning(f"⚠️ [SESSION_CREATE] Failed to fetch user role: {role_response.status_code}")
                    logger.warning(f"⚠️ [SESSION_CREATE] Response body: {role_response.text}")
                    user_data['role'] = 'user'
                    user_data['roles'] = ['user']
        except Exception as e:
            logger.error(f"❌ [SESSION_CREATE] Exception while fetching user role: {e}")
            logger.error(f"❌ [SESSION_CREATE] Exception type: {type(e).__name__}")
            import traceback
            logger.error(f"❌ [SESSION_CREATE] Traceback: {traceback.format_exc()}")
            user_data['role'] = 'user'  # Default to user if role fetch fails
            user_data['roles'] = ['user']
        
        # Get client IP and User-Agent for session binding
        ip_address = req.client.host if req.client else None
        user_agent = req.headers.get("user-agent")
        
        # Create session with security metadata
        session_id = create_session(user_data, ip_address, user_agent)
        logger.info(f"✅ [SESSION_CREATE] Session created with ID: {session_id[:16]}...")
        
        # Determine SameSite policy based on context
        context = request.context or "admin"
        if context == "widget":
            # Widget embedded in iframe on different domains
            # MUST use SameSite=None for cross-site cookies
            samesite_policy = "none"
            logger.info(f"🔧 Using SameSite=None for widget context (cross-site iframe)")
        else:
            # Admin/Agent screens on same domain
            # Use SameSite=Lax for better security
            samesite_policy = "lax"
            logger.info(f"🔧 Using SameSite=Lax for admin context (same-site)")
        
        # Set httpOnly, secure cookie with context-appropriate SameSite policy
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            max_age=SESSION_MAX_AGE,
            httponly=True,   # JavaScript cannot access (XSS protection)
            secure=True,     # Only sent over HTTPS (MITM protection) - REQUIRED for SameSite=None
            samesite=samesite_policy,  # Context-aware: "lax" for admin, "none" for widget
            domain=SESSION_DOMAIN,  # Works for all *.globistaan.com subdomains
            path="/"         # Cookie sent for all paths
        )
        
        logger.info(
            f"✅ [SESSION_CREATE] Session cookie set for user {user_data.get('email')} "
            f"from IP {ip_address} (context={context}, samesite={samesite_policy}, domain={SESSION_DOMAIN})"
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
        logger.error(f"❌ [SESSION_CREATE] Error creating session: {e}")
        import traceback
        logger.error(f"❌ [SESSION_CREATE] Traceback: {traceback.format_exc()}")
        raise HTTPException(
            status_code=500,
            detail="Failed to create session"
        )


@router.post("/auth/logout")
async def logout(request: Request, response: Response):
    """
    Logout and clear session cookie.
    
    Deletes the session from storage and clears the cookie.
    """
    try:
        # Get session ID from cookie
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        
        if session_id:
            # Delete session from storage
            delete_session(session_id)
        
        # Clear cookie (set expired cookie)
        response.delete_cookie(
            key=SESSION_COOKIE_NAME,
            domain=SESSION_DOMAIN,
            path="/"
        )
        
        logger.info("✅ User logged out successfully")
        
        return {
            "success": True,
            "message": "Logged out successfully"
        }
        
    except Exception as e:
        logger.error(f"❌ Error during logout: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to logout"
        )


@router.get("/auth/me")
async def get_current_user(request: Request):
    """
    Get current user from session cookie.
    
    Returns user data if session is valid, 401 if not authenticated.
    Validates IP and User-Agent to detect session hijacking.
    """
    try:
        # Get session ID from cookie
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        
        if not session_id:
            raise HTTPException(
                status_code=401,
                detail="Not authenticated"
            )
        
        # Get client IP and User-Agent for validation
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent")
        
        # Get session data with security validation
        session_data = get_session(session_id, ip_address, user_agent, validate_security=True)
        
        if not session_data:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired session"
            )
        
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
        logger.error(f"❌ Error getting current user: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to get user"
        )


@router.post("/auth/refresh")
async def refresh_session(request: Request, response: Response):
    """
    Refresh session cookie to extend expiration.
    
    Call this periodically (e.g., every 30 minutes) to keep user logged in.
    """
    try:
        # Get session ID from cookie
        session_id = request.cookies.get(SESSION_COOKIE_NAME)
        
        if not session_id:
            raise HTTPException(
                status_code=401,
                detail="Not authenticated"
            )
        
        # Get session data
        session_data = get_session(session_id)
        
        if not session_data:
            raise HTTPException(
                status_code=401,
                detail="Invalid or expired session"
            )
        
        # Get session store
        store = get_session_store()
        
        # Extend session expiration
        session_data["expires_at"] = int(time.time()) + SESSION_MAX_AGE
        store.update_ttl(session_id, SESSION_MAX_AGE)
        
        # Reset cookie with new expiration
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            max_age=SESSION_MAX_AGE,
            httponly=True,
            secure=True,
            samesite="lax",
            domain=SESSION_DOMAIN,
            path="/"
        )
        
        logger.info(f"✅ Session refreshed for user {session_data['email']}")
        
        return {
            "success": True,
            "message": "Session refreshed"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"❌ Error refreshing session: {e}")
        raise HTTPException(
            status_code=500,
            detail="Failed to refresh session"
        )


# Export session functions for use in middleware
__all__ = ['router', 'get_session', 'SESSION_COOKIE_NAME']
