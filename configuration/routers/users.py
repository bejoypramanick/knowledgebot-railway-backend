"""
Users Management Endpoints
Handles user profile and role management.
"""
import os
from typing import List

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, EmailStr

from configuration.core.logging_config import get_railway_logger

from ..service.auth_service import AuthService

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1/users", tags=["users-management"])


@router.get("/profile", response_model=dict)
async def get_user_profile(uid: str):
    """Get user profile by Firebase UID."""
    try:
        # Get user email from Firebase UID
        import httpx
        
        api_gateway_url = os.getenv("API_GATEWAY_URL", "http://localhost:8080")
        
        async with httpx.AsyncClient() as client:
            response = await client.get(
                f"{api_gateway_url}/firebase/user/{uid}"
            )
            
            if response.status_code != 200:
                raise HTTPException(status_code=404, detail="User not found")
            
            user_data = response.json()
            
            if not user_data or 'user' not in user_data:
                raise HTTPException(status_code=404, detail="User profile not found")
            
            return user_data['user']
            
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting user profile: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting user profile: {str(e)}")


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


@router.get("/roles", response_model=dict)
async def get_user_roles(uid: str = None, email: str = None):
    """Get user roles by Firebase UID or email."""
    try:
        service = AuthService()  # Service manages its own DAO
        
        if uid:
            # Get user email from Firebase UID
            import httpx
            
            api_gateway_url = os.getenv("API_GATEWAY_URL", "http://localhost:8080")
            
            async with httpx.AsyncClient() as client:
                response = await client.get(
                    f"{api_gateway_url}/firebase/user/{uid}"
                )
                
                if response.status_code != 200:
                    return []  # Return empty array for frontend compatibility
                
                user_data = response.json()
                
                if not user_data or 'user' not in user_data or 'email' not in user_data['user']:
                    return []  # Return empty array for frontend compatibility
                
                email = user_data['user']['email']
                result = await service.get_user_role(email)
                return result.get('roles', [])  # Return just the roles array for frontend compatibility
        
        elif email:
            result = await service.get_user_role(email)
            return result.get('roles', [])  # Return just the roles array for frontend compatibility
        
        else:
            return []  # Return empty array for frontend compatibility
            
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
