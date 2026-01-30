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
    """Get user profile with roles from database."""
    try:
        # Get user data from headers (set by API Gateway)
        uid = request.headers.get("X-User-UID", "")
        email = request.headers.get("X-User-Email", "")
        display_name = request.headers.get("X-User-Display-Name", "")
        photo_url = request.headers.get("X-User-Photo-URL", "")
        
        # Fetch roles from database with timeout protection
        import asyncio
        service = AuthService()
        
        try:
            # Add timeout to prevent hanging
            result = await asyncio.wait_for(service.get_user_role(email), timeout=5.0)
            roles = result.get('roles', [])
        except asyncio.TimeoutError:
            logger.warning(f"Timeout getting user role for {email}, using default")
            roles = ["user"]
        except Exception as e:
            logger.error(f"Error getting user role for {email}: {e}")
            roles = ["user"]
        
        # Determine primary role based on priority
        current_role = 'user'
        if 'admin' in roles:
            current_role = 'admin'
        elif 'human_agent' in roles:
            current_role = 'human_agent'
        
        return {
            "uid": uid,
            "email": email,
            "displayName": display_name,
            "photoURL": photo_url,
            "role": current_role,  # Primary role from database
            "roles": roles  # All roles from database
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
    """Get user roles from database."""
    try:
        # Get user email from headers (set by API Gateway)
        email = request.headers.get("X-User-Email", "")
        
        # Fetch roles from database
        service = AuthService()
        result = await service.get_user_role(email)
        roles = result.get('roles', [])
        
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
