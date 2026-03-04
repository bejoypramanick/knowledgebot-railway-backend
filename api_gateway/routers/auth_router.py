"""
Authentication Router
Handles session creation, logout, and user info with httpOnly cookies
"""
from fastapi import APIRouter, HTTPException, Response, Request
from pydantic import BaseModel
import secrets
import time
from typing import Optional, Dict, Any
import os

from api_gateway.core.firebase_auth import verify_firebase_token
from api_gateway.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)
router = APIRouter()

# Session storage (use Redis in production - see below)
# For now, using in-memory dict for simplicity
# Format: {session_id: {uid, email, name, picture, created_at, expires_at}}
_sessions: Dict[str, Dict[str, Any]] = {}

# Session configuration
SESSION_COOKIE_NAME = "session"
SESSION_MAX_AGE = 60 * 60 * 24 * 7  # 7 days in seconds
SESSION_DOMAIN = ".globistaan.com"  # Works for all *.globistaan.com subdomains


class CreateSessionRequest(BaseModel):
    """Request body for creating a session from Firebase ID token"""
    idToken: str


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
    session_data = _sessions.get(session_id)
    
    if not session_data:
        return None
    
    # Check if session expired
    if session_data["expires_at"] < int(time.time()):
        # Session expired, delete it
        del _sessions[session_id]
        logger.info(f"⏰ Session expired for {session_data.get('email')}")
        return None
    
    # Security validation (detect session hijacking)
    if validate_security:
        # Check IP address match (with flexibility for mobile networks)
        if ip_address and session_data.get("ip_address"):
            if ip_address != session_data["ip_address"]:
                logger.warning(
                    f"🚨 IP address mismatch for {session_data.get('email')}: "
                    f"expected {session_data['ip_address']}, got {ip_address}"
                )
                # For now, just log warning (don't invalidate)
                # In production, you might want to invalidate or require re-auth
                # Uncomment below to enforce strict IP binding:
                # del _sessions[session_id]
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
                # del _sessions[session_id]
                # return None
    
    # Update request tracking
    session_data["request_count"] = session_data.get("request_count", 0) + 1
    session_data["last_request_time"] = int(time.time())
    
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
    
    # Store session data with security metadata
    _sessions[session_id] = {
        "uid": user_data.get("uid"),
        "email": user_data.get("email"),
        "name": user_data.get("name", user_data.get("email")),
        "picture": user_data.get("picture"),
        "created_at": int(time.time()),
        "expires_at": int(time.time()) + SESSION_MAX_AGE,
        # Security: Bind session to IP and User Agent
        "ip_address": ip_address,
        "user_agent": user_agent,
        "request_count": 0,
        "last_request_time": int(time.time())
    }
    
    logger.info(f"✅ Session created for user {user_data.get('email')} from IP {ip_address} (expires in {SESSION_MAX_AGE}s)")
    
    return session_id


def delete_session(session_id: str) -> bool:
    """Delete a session"""
    if session_id in _sessions:
        del _sessions[session_id]
        logger.info(f"✅ Session {session_id[:8]}... deleted")
        return True
    return False


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
    2. Frontend calls this endpoint with the token
    3. Backend verifies token with Firebase Admin SDK
    4. Backend creates session and sets httpOnly, secure, SameSite cookie
    5. Frontend uses cookie for all subsequent requests (automatic)
    
    Security:
    - Binds session to IP address and User-Agent
    - Detects session hijacking attempts
    
    Returns:
        User data (uid, email, name, picture)
    """
    try:
        # Verify Firebase ID token
        user_data = verify_firebase_token(request.idToken)
        
        if not user_data:
            logger.warning("❌ Invalid Firebase ID token provided")
            raise HTTPException(
                status_code=401,
                detail="Invalid Firebase ID token"
            )
        
        # Get client IP and User-Agent for session binding
        ip_address = req.client.host if req.client else None
        user_agent = req.headers.get("user-agent")
        
        # Create session with security metadata
        session_id = create_session(user_data, ip_address, user_agent)
        
        # Set httpOnly, secure, SameSite cookie
        response.set_cookie(
            key=SESSION_COOKIE_NAME,
            value=session_id,
            max_age=SESSION_MAX_AGE,
            httponly=True,   # JavaScript cannot access (XSS protection)
            secure=True,     # Only sent over HTTPS (MITM protection)
            samesite="lax",  # CSRF protection (sent on top-level navigation)
            domain=SESSION_DOMAIN,  # Works for all *.globistaan.com subdomains
            path="/"         # Cookie sent for all paths
        )
        
        logger.info(f"✅ Session cookie set for user {user_data.get('email')} from IP {ip_address}")
        
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
        logger.error(f"❌ Error creating session: {e}")
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
        
        # Extend session expiration
        _sessions[session_id]["expires_at"] = int(time.time()) + SESSION_MAX_AGE
        
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
