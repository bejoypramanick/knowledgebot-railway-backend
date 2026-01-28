"""
FastAPI Authentication Middleware
Verifies Firebase Auth tokens and protects endpoints.
"""
from typing import Any, Dict, Optional

from fastapi import HTTPException, Security
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from shared.firebase_auth import verify_firebase_token
from shared.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

# HTTP Bearer token security scheme (required auth)
security = HTTPBearer()

# HTTP Bearer token security scheme (optional auth)
security_optional = HTTPBearer(auto_error=False)


async def get_current_user(
    credentials: HTTPAuthorizationCredentials = Security(security)
) -> Dict[str, Any]:
    """
    Dependency to get current authenticated user from Firebase token.
    
    Usage:
        @router.get("/protected")
        async def protected_route(user: dict = Depends(get_current_user)):
            return {"user_id": user["uid"]}
    """
    token = credentials.credentials
    
    decoded_token = verify_firebase_token(token)
    if not decoded_token:
        raise HTTPException(
            status_code=401,
            detail="Invalid or expired authentication token"
        )
    
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

