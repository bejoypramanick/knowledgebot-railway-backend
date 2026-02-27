"""
FastAPI Authentication Middleware
Verifies Firebase Auth tokens and protects endpoints.
Includes admin session tracking for audit trail.
"""
import logging
import uuid
from typing import Any, Dict, Optional
from datetime import datetime

from fastapi import Depends, HTTPException, Security, status, Request
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api_gateway.core.firebase_auth import verify_firebase_token
from shared.correlation_id import get_correlation_id, add_correlation_id_headers
from shared.otel_logger import get_otel_logger, set_admin_context, clear_admin_context

logger = logging.getLogger(__name__)
otel_logger = get_otel_logger("auth_middleware", "api_gateway")

# HTTP Bearer token security scheme (required auth)
security = HTTPBearer()

# HTTP Bearer token security scheme (optional auth)
security_optional = HTTPBearer(auto_error=False)


def _parse_user_agent(user_agent: str) -> Dict[str, str]:
    """Parse user agent string to extract browser, OS, and device type.

    Simple parser without external dependencies.
    Returns dict with 'browser', 'os', 'device_type' keys.
    """
    ua = user_agent.lower() if user_agent else ""

    # Detect browser
    browser = "Unknown"
    if "chrome" in ua and "edg" not in ua:
        browser = "Chrome"
    elif "firefox" in ua:
        browser = "Firefox"
    elif "safari" in ua and "chrome" not in ua:
        browser = "Safari"
    elif "edg" in ua:
        browser = "Edge"
    elif "opera" in ua or "opr/" in ua:
        browser = "Opera"

    # Detect OS
    os_name = "Unknown"
    if "windows" in ua:
        os_name = "Windows"
    elif "mac" in ua:
        os_name = "macOS"
    elif "linux" in ua:
        os_name = "Linux"
    elif "iphone" in ua:
        os_name = "iOS"
    elif "android" in ua:
        os_name = "Android"

    # Detect device type
    device_type = "Desktop"
    if "mobile" in ua or "iphone" in ua or "android" in ua or "webos" in ua:
        device_type = "Mobile"
    elif "ipad" in ua or "tablet" in ua:
        device_type = "Tablet"

    return {
        "browser": browser,
        "os": os_name,
        "device_type": device_type
    }


async def ensure_admin_session(request: Request, decoded_token: Dict[str, Any]) -> Optional[str]:
    """
    Create/retrieve admin session if user has admin or agent role.
    Returns session_id if admin/agent, None otherwise.
    """
    email = decoded_token.get("email", "")

    # Skip session creation for non-admin users
    # This will be checked by configuration service roles

    try:
        # Get user roles from configuration service
        roles = await get_user_roles(email)
        is_admin = "admin" in roles or "human_agent" in roles

        if not is_admin:
            return None

        # Generate session ID
        session_id = str(uuid.uuid4())

        # Extract metadata from request
        ip_address = request.client.host if request.client else None
        user_agent = request.headers.get("user-agent", "")
        ua_parsed = _parse_user_agent(user_agent)

        # Get JWT expiration (convert from epoch to datetime)
        exp_timestamp = decoded_token.get("exp", 0)
        expires_at = datetime.fromtimestamp(exp_timestamp)

        # Get primary role
        role_name = "admin" if "admin" in roles else "human_agent"

        # Create session via configuration service
        import httpx
        import os

        config_service_url = os.getenv("CONFIGURATION_SERVICE_URL", "http://localhost:8001")
        correlation_id = get_correlation_id()

        headers = {}
        if correlation_id:
            add_correlation_id_headers(headers, correlation_id)

        # Forward auth header for session creation endpoint
        auth_header = request.headers.get("authorization", "")
        if auth_header:
            headers["authorization"] = auth_header

        session_data = {
            "session_id": session_id,
            "email": email,
            "role_name": role_name,
            "ip_address": ip_address,
            "user_agent": user_agent,
            "browser": ua_parsed.get("browser"),
            "os": ua_parsed.get("os"),
            "device_type": ua_parsed.get("device_type"),
            "expires_at": expires_at.isoformat()
        }

        async with httpx.AsyncClient() as client:
            response = await client.post(
                f"{config_service_url}/api/v1/admin/sessions/create",
                json=session_data,
                headers=headers,
                timeout=5.0
            )

            if response.status_code == 200:
                result = response.json()
                created_session_id = result.get("session_id", session_id)
                otel_logger.info(f"✅ Admin session created: {email} ({role_name})")
                return created_session_id
            else:
                otel_logger.warning(f"⚠️ Failed to create admin session for {email}: {response.status_code}")
                # Still return session_id for context tracking even if DB creation fails
                return session_id

    except Exception as e:
        otel_logger.error(f"❌ Error creating admin session for {email}: {e}")
        # Return session_id anyway to not break authentication
        return str(uuid.uuid4())


async def get_user_roles(email: str) -> list:
    """Get user roles from configuration service."""
    try:
        import httpx
        import os
        
        config_service_url = os.getenv("CONFIGURATION_SERVICE_URL", "http://localhost:8001")
        correlation_id = get_correlation_id()
        
        headers = {}
        if correlation_id:
            add_correlation_id_headers(headers, correlation_id)
            logger.info(f"🔍 [{correlation_id}] Getting roles for user {email}")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{config_service_url}/api/v1/admin/user-role/{email}",
                headers=headers,
                timeout=10.0
            )
            
            if response.status_code == 200:
                roles_data = response.json()
                return roles_data.get("roles", ["user"])
            else:
                return ["user"]
    except Exception as e:
        logger.error(f"Error getting user roles for {email}: {e}")
        return ["user"]


async def get_current_user(
    request: Request,
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> Dict[str, Any]:
    """
    Dependency to get current authenticated user from Firebase token.
    Creates admin session if user has admin/agent role.

    Usage:
        @router.get("/protected")
        async def protected_route(user: dict = Depends(get_current_user)):
            return {"user_id": user["uid"], "email": user["email"]}
    """
    token = credentials.credentials
    correlation_id = get_correlation_id()

    decoded_token = verify_firebase_token(token)
    if not decoded_token:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token"
        )

    # Create admin session if user is admin/agent
    session_id = await ensure_admin_session(request, decoded_token)
    if session_id:
        # Get roles to determine admin role
        email = decoded_token.get("email", "")
        roles = await get_user_roles(email)
        role_name = "admin" if "admin" in roles else "human_agent"

        # Set OTEL context for admin
        set_admin_context(session_id, email, role_name)
        otel_logger.info(f"🔍 Admin context set: {email} ({role_name})")

    if correlation_id:
        logger.info(f"🔍 [{correlation_id}] Authenticated user {decoded_token['email']}")

    return decoded_token


async def get_optional_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security_optional)
) -> Optional[Dict[str, Any]]:
    """
    Dependency to optionally get current user (doesn't require auth).
    
    Usage:
        @router.get("/public")
        async def public_route(user: Optional[dict] = Depends(get_optional_user)):
            if user:
                return {"authenticated": True, "user_id": user["uid"]}
            return {"authenticated": False}
    """
    if not credentials:
        return None
    
    token = credentials.credentials
    decoded_token = verify_firebase_token(token)
    return decoded_token

