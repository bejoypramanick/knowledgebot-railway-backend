"""
Admin Management Endpoints
Handles admin user creation, verification, and role management.
"""
from fastapi import APIRouter, HTTPException, Depends
from pydantic import BaseModel, EmailStr
from typing import List, Optional
import secrets
from shared.logging_config import get_railway_logger
import logging

from shared.firebase_auth import get_user_from_firestore, save_user_to_firestore, update_user_role_in_firestore
from shared.auth_middleware import get_current_user
from ..service.auth_service import AuthService

logger = get_railway_logger(__name__)

router = APIRouter(prefix="/api/v1/admin", tags=["admin-management"])


class AdminRequest(BaseModel):
    emails: List[EmailStr]


class ConfirmAdminRequest(BaseModel):
    token: str


def generate_confirmation_token() -> str:
    """Generate a secure confirmation token."""
    return secrets.token_urlsafe(32)


@router.post("/admins", response_model=dict)
async def add_admins(request: AdminRequest, current_user: dict = Depends(get_current_user)):
    """Add admin users and send confirmation emails. Only existing admins can add new admins."""
    # Verify current user is an admin
    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=403, detail="User email not found in token")
    
    try:
        service = AuthService()  # Service manages its own DAO
        result = await service.add_admins(request.emails, user_email)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error adding admins: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error adding admins: {str(e)}")


# Admin confirmation endpoint removed - admins are now activated immediately


@router.get("/admins", response_model=dict)
async def list_admins(current_user: dict = Depends(get_current_user)):
    """List all admins. Only admins can view this list."""
    # Verify current user is an admin
    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=403, detail="User email not found in token")
    
    try:
        auth_service = AuthService()  # Service manages its own DAO
        
        # Check if current user is an admin
        is_admin = await auth_service.check_admin_exists(user_email)
        
        if not is_admin or is_admin == 0:
            raise HTTPException(status_code=403, detail="Only admins can view admin list")
        
        # Get all admins
        admins = await auth_service.list_all_admins()
        
        return {
            "success": True,
                "admins": [
                    {
                        "email": admin['email'],
                        "created_at": admin['created_at'].isoformat() if admin['created_at'] else None,
                        "created_by": admin['created_by_email']
                    }
                    for admin in admins
                ]
            }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error listing admins: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error listing admins: {str(e)}")


@router.delete("/admins/{email}", response_model=dict)
async def remove_admin(email: str, current_user: dict = Depends(get_current_user)):
    """Remove an admin. Only admins can remove other admins."""
    # Verify current user is an admin
    user_email = current_user.get('email')
    if not user_email:
        raise HTTPException(status_code=403, detail="User email not found in token")
    
    try:
        auth_service = AuthService()  # Service manages its own DAO
        result = await auth_service.remove_admin(email, user_email)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error removing admin: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error removing admin: {str(e)}")


@router.get("/user-role/{email}", response_model=dict)
async def get_user_role(email: str):
    """Get user role (admin, human_agent, or user) for a given email."""
    try:
        service = AuthService()  # Service manages its own DAO
        return await service.get_user_role(email)
    except Exception as e:
        logger.error(f"Error getting user role: {e}", exc_info=True)
        raise HTTPException(status_code=500, detail=f"Error getting user role: {str(e)}")
