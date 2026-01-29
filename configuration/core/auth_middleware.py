"""
Authentication Middleware for Firebase Token Verification
Provides reusable decorator and middleware functions for API endpoints
"""
from functools import wraps
from typing import Callable, Optional

from fastapi import HTTPException, Request, status
from configuration.core.firebase_auth import verify_firebase_token
from configuration.core.logging_config import get_railway_logger

logger = get_railway_logger(__name__)

async def get_user_from_token(request: Request) -> Optional[dict]:
    """Extract and verify Firebase token from request, return user data"""
    try:
        # Extract Firebase token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return None
        
        token = auth_header.split(" ")[1]
        
        # Verify Firebase token and extract user data
        user_data = verify_firebase_token(token)
        
        if not user_data:
            return None
        
        return user_data
        
    except Exception as e:
        logger.error(f"Error verifying Firebase token: {e}")
        return None

def require_auth(roles: Optional[list] = None):
    """Decorator to require Firebase authentication and optional role verification"""
    def decorator(func: Callable):
        @wraps(func)
        async def wrapper(request: Request, *args, **kwargs):
            # Get user from token
            user_data = await get_user_from_token(request)
            
            if not user_data:
                raise HTTPException(
                    status_code=status.HTTP_401_UNAUTHORIZED,
                    detail="Invalid or missing authentication token"
                )
            
            # Add user data to request state for endpoint to use
            request.state.user = user_data
            
            # If roles specified, verify user has required role
            if roles:
                from ..service.auth_service import AuthService
                service = AuthService()
                result = await service.get_user_role(user_data['email'])
                user_roles = result.get('roles', [])
                
                # Check if user has any of the required roles
                if not any(role in user_roles for role in roles):
                    raise HTTPException(
                        status_code=status.HTTP_403_FORBIDDEN,
                        detail=f"Access denied. Required roles: {roles}"
                    )
            
            return await func(request, *args, **kwargs)
        return wrapper
    return decorator

def require_role(role: str):
    """Decorator to require specific role"""
    return require_auth([role])

def require_admin():
    """Decorator to require admin role"""
    return require_role("admin")

def require_human_agent():
    """Decorator to require human_agent role"""
    return require_role("human_agent") or require_role("admin")
