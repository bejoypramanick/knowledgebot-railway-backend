"""
FastAPI Authentication Middleware
Verifies Firebase Auth tokens and protects endpoints.
"""
from typing import Any, Dict, Optional

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from api_gateway.core.firebase_auth import verify_firebase_token
from api_gateway.core.logging_config import get_railway_logger
from api_gateway.core.correlation_id import get_correlation_id, add_correlation_id_headers

logger = get_railway_logger(__name__)

# HTTP Bearer token security scheme (required auth)
security = HTTPBearer()

# HTTP Bearer token security scheme (optional auth)
security_optional = HTTPBearer(auto_error=False)


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
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> Dict[str, Any]:
    """
    Dependency to get current authenticated user from Firebase token with roles.
    
    Usage:
        @router.get("/protected")
        async def protected_route(user: dict = Depends(get_current_user)):
            return {"user_id": user["uid"], "roles": user["roles"]}
    """
    token = credentials.credentials
    correlation_id = get_correlation_id()
    
    decoded_token = verify_firebase_token(token)
    if not decoded_token:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token"
        )
    
    # Add user roles
    decoded_token["roles"] = await get_user_roles(decoded_token["email"])
    
    if correlation_id:
        logger.info(f"🔍 [{correlation_id}] Authenticated user {decoded_token['email']} with roles {decoded_token['roles']}")
    
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

