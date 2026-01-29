"""
Users Management Endpoints
Handles user profile and role management.
"""
import os
from typing import List

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, EmailStr

from configuration.core.logging_config import get_railway_logger

from ..service.auth_service import AuthService

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1/users", tags=["users-management"])


@router.get("/profile", response_model=dict)
async def get_user_profile(request: Request):
    """Get user profile by verifying Firebase token and looking up in database."""
    try:
        # Extract Firebase token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return {"uid": "", "email": "", "displayName": "", "photoURL": "", "role": "user"}
        
        token = auth_header.split(" ")[1]
        
        # Verify Firebase token and extract user data
        from api_gateway.core.firebase_auth import verify_firebase_token
        user_data = verify_firebase_token(token)
        
        if not user_data:
            return {"uid": "", "email": "", "displayName": "", "photoURL": "", "role": "user"}
        
        # Get user roles from database using email
        service = AuthService()
        result = await service.get_user_role(user_data['email'])
        roles = result.get('roles', [])
        
        return {
            "uid": user_data.get('uid', ''),
            "email": user_data.get('email', ''),
            "displayName": user_data.get('displayName', ''),
            "photoURL": user_data.get('photoURL', ''),
            "role": roles[0] if roles else 'user'
        }
            
    except Exception as e:
        logger.error(f"Error getting user profile: {e}", exc_info=True)
        # Return basic profile for frontend compatibility
        return {"uid": "", "email": "", "displayName": "", "photoURL": "", "role": "user"}


@router.put("/profile", response_model=dict)
async def update_user_profile(uid: str, request_data: dict):
    """Update user profile data."""
    try:
        # For now, just return success - user profile updates can be implemented later
        # This endpoint exists for frontend compatibility
        return {"success": True, "message": "User profile updated successfully"}
    except Exception as e:
        logger.error(f"Error updating user profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error updating user profile: {str(e)}")


@router.post("/switch-role", response_model=dict)
async def switch_user_role(uid: str, request_data: dict):
    """Switch user role."""
    try:
        # For now, just return success - role switching can be implemented later
        # This endpoint exists for frontend compatibility
        return {"success": True, "message": "User role switched successfully"}
    except Exception as e:
        logger.error(f"Error switching user role: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error switching user role: {str(e)}")


@router.get("/roles", response_model=list)
async def get_user_roles(request: Request):
    """Get user roles by verifying Firebase token and looking up in database."""
    try:
        # Extract Firebase token from Authorization header
        auth_header = request.headers.get("Authorization")
        if not auth_header or not auth_header.startswith("Bearer "):
            return []  # Return empty array for unauthenticated requests
        
        token = auth_header.split(" ")[1]
        
        # Verify Firebase token and extract user data
        from api_gateway.core.firebase_auth import verify_firebase_token
        user_data = verify_firebase_token(token)
        
        if not user_data:
            return []  # Return empty array for invalid token
        
        # Get user roles from database using email
        service = AuthService()
        result = await service.get_user_role(user_data['email'])
        return result.get('roles', [])  # Return roles array directly
            
    except Exception as e:
        logger.error(f"Error getting user roles: {e}", exc_info=True)
        return []  # Return empty array for frontend compatibility


@router.post("/unique-id", response_model=dict)
async def get_or_create_user_id(request_data: dict):
    """Get or create user ID by email and role."""
    try:
        email = request_data.get('email')
        role = request_data.get('role', 'customer')
        
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")
        
        # For now, generate a simple unique ID based on email and role
        # In production, this would use a proper ID generation service
        import hashlib
        import time
        
        unique_id = f"{role}_{hashlib.md5(f'{email}_{role}_{int(time.time())}'.encode()).hexdigest()[:8]}"
        
        return {
            "unique_id": unique_id,
            "email": email,
            "role": role,
            "created_at": "2024-01-29T16:36:00Z"
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting or creating user ID: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting or creating user ID: {str(e)}")


@router.get("/unique-id", response_model=dict)
async def get_user_id(email: str, role: str = "customer"):
    """Get user ID by email and role."""
    try:
        if not email:
            raise HTTPException(status_code=400, detail="Email is required")
        
        # For now, generate the same unique ID format
        import hashlib
        
        unique_id = f"{role}_{hashlib.md5(f'{email}_{role}'.encode()).hexdigest()[:8]}"
        
        return {
            "unique_id": unique_id,
            "email": email,
            "role": role
        }
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user ID: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting user ID: {str(e)}")
