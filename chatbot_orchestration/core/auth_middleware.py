"""
Authentication Middleware for Chatbot Orchestration
Provides reusable decorators for Firebase token verification
"""
from functools import wraps
from typing import Callable, Optional

from fastapi import HTTPException, Request, status
from chatbot_orchestration.core.firebase_auth import verify_firebase_token
from chatbot_orchestration.core.logging_config import get_railway_logger

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

def require_auth():
    """Decorator to require Firebase authentication for chat endpoints"""
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
            
            return await func(request, *args, **kwargs)
        return wrapper
    return decorator
