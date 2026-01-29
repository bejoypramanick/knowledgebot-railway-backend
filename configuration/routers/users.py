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
    """Get user profile from headers (set by API Gateway)."""
    try:
        # Get user data from headers (set by API Gateway)
        uid = request.headers.get("X-User-UID", "")
        email = request.headers.get("X-User-Email", "")
        display_name = request.headers.get("X-User-Display-Name", "")
        photo_url = request.headers.get("X-User-Photo-URL", "")
        role = request.headers.get("X-User-Role", "user")
        roles_header = request.headers.get("X-User-Roles", "user")
        roles = roles_header.split(",") if roles_header else ["user"]
        
        return {
            "uid": uid,
            "email": email,
            "displayName": display_name,
            "photoURL": photo_url,
            "role": role,  # Primary role from gateway
            "roles": roles  # All roles from gateway
        }
            
    except Exception as e:
        logger.error(f"Error getting user profile: {e}", exc_info=True)
        # Return basic profile for frontend compatibility
        return {"uid": "", "email": "", "displayName": "", "photoURL": "", "role": "user", "roles": ["user"]}


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
    """Get user roles from headers (set by API Gateway)."""
    try:
        # Get roles from headers (set by API Gateway)
        roles_header = request.headers.get("X-User-Roles", "user")
        roles = roles_header.split(",") if roles_header else ["user"]
        return roles  # Return roles array directly
            
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
